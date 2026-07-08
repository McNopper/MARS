"""Native MARS-to-MARS federation.

Connects MARS nodes over a dedicated TCP port (line-delimited JSON) so that the
agents, skills, MCP servers and models of several machines form one shared pool.
Remote agents are mirrored locally as *virtual* participants and become
addressable exactly like local agents, and the skill index spans every peer.

Design
------
Each remote agent owned by a peer is represented on the consuming node as a
virtual :class:`ClientSession` whose writer (:class:`FederationWriter`) forwards
anything the router delivers to it across the federation link.  This lets the
existing :meth:`MARSServer._route_message` routing handle federated traffic with
no special cases — a message *to* a federated agent is written to its virtual
session and forwarded as ``fed_msg``; the owning node routes it to the real
agent through a virtual *caller* session whose reply is forwarded back as
``fed_reply``.

Wire frames (one JSON object per line)::

    {"t": "fed_hello",   "node": <id>, "agents": [<info>, ...]}
    {"t": "fed_spawn",   "agent": <info>}
    {"t": "fed_despawn", "agent_id": <remote-local-id>}
    {"t": "fed_msg",     "msg_id": <id>, "to": <remote-local-id>, "from": <sender>, "text": <str>}
    {"t": "fed_reply",   "msg_id": <id>, "to": <sender>, "from": <agent>, "text": <str>}

where ``<info>`` is ``{"agent_id", "agent_type", "skills", "model", "vendor"}``.

Scope (v1): direct addressing of remote agents + skill propagation.  Cross-node
*rooms* and artifact relay are intentionally out of scope and are not routed.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from mars.common.models import AgentRecord, ChatMessage
from mars.common.wire import decode_frame, encode_frame, iter_frames

logger = logging.getLogger(__name__)

# Separator between a peer node id and a remote agent id in a federated local id.
FED_SEP = "/"

# How long the owning node waits for a real agent to answer a federated request
# before it returns a synthetic error reply and reclaims the request's resources.
# This bounds the lifetime of per-request virtual caller sessions and pending maps.
FED_REQUEST_TIMEOUT = 300.0


class FederationWriter:
    """Minimal ``asyncio.StreamWriter`` stand-in for a virtual session.

    The router writes line-delimited JSON frames to a session's ``writer``.  For
    virtual (federated) sessions we capture those frames and hand them to
    *on_frame* instead of sending them over a socket.
    """

    def __init__(self, on_frame: Callable[[dict[str, Any]], None]) -> None:
        self._on_frame = on_frame
        self._closing = False

    def write(self, data: bytes) -> None:
        if self._closing:
            return
        try:
            text = bytes(data).decode("utf-8")
        except Exception:
            return
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            frame = decode_frame(line)
            if frame is None:
                continue
            with contextlib.suppress(Exception):
                self._on_frame(frame)

    def is_closing(self) -> bool:
        return self._closing

    def close(self) -> None:
        self._closing = True

    async def wait_closed(self) -> None:
        return

    def get_extra_info(self, name: str, default: Any = None) -> Any:
        return default


@dataclass
class FederationPeer:
    """Bookkeeping for one connected peer node."""

    writer: Any                                   # real asyncio.StreamWriter to the peer
    node: str | None = None
    # consuming side: local ids of virtual agent sessions mirroring this peer
    virtual_agents: set[str] = field(default_factory=set)
    # consuming side: msg_id -> local sender id awaiting a reply
    pending_out: dict[str, str] = field(default_factory=dict)
    # owning side: per-request virtual caller id -> request bookkeeping
    #   {"msg_id", "frm", "to", "session", "timer"}
    requests: dict[str, dict[str, Any]] = field(default_factory=dict)


class FederationManager:
    """Manages federation peer links and mirrors remote agents locally."""

    def __init__(self, server: Any, node_id: str) -> None:
        self._server = server
        self.node_id = node_id
        self._peers: dict[str, FederationPeer] = {}

    # ── Local snapshot ────────────────────────────────────────────────────────

    def _local_snapshot(self) -> list[dict[str, Any]]:
        """Info for every locally-owned (non-federated) agent."""
        out: list[dict[str, Any]] = []
        for aid, rec in list(self._server._state.agents.items()):
            if getattr(rec, "domain", "") == "federated":
                continue
            if getattr(rec, "agent_type", "") == "HumanUser":
                continue
            out.append(self._agent_info(rec))
        return out

    @staticmethod
    def _agent_info(rec: AgentRecord) -> dict[str, Any]:
        return {
            "agent_id": rec.agent_id,
            "agent_type": rec.agent_type,
            "skills": list(rec.skills or []),
            "model": rec.model,
            "vendor": rec.vendor,
        }

    # ── Transport ─────────────────────────────────────────────────────────────

    def _send(self, writer: Any, frame: dict[str, Any]) -> None:
        try:
            if writer.is_closing():
                return
            writer.write(encode_frame(frame))
        except Exception:
            pass

    async def serve(self, host: str, port: int) -> None:
        srv = await asyncio.start_server(
            self._serve_peer, host, port, limit=16 * 1024 * 1024
        )
        print(f"Federation listening on {host}:{port}", flush=True)
        async with srv:
            await srv.serve_forever()

    async def connect(self, host: str, port: int) -> str:
        try:
            reader, writer = await asyncio.open_connection(host, port)
        except Exception as exc:
            logger.warning("Federation connect to %s:%s failed: %s", host, port, exc)
            return f"Federation connect to {host}:{port} failed: {exc}"
        asyncio.create_task(self._serve_peer(reader, writer))
        return f"Federating with {host}:{port}"

    async def _serve_peer(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        # Greet immediately with our identity + agent snapshot (both directions).
        self._send(writer, {
            "t": "fed_hello",
            "node": self.node_id,
            "agents": self._local_snapshot(),
        })
        peer = FederationPeer(writer=writer)
        try:
            async for frame in iter_frames(reader):
                await self._dispatch(peer, frame)
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            pass
        finally:
            self._cleanup_peer(peer)
            with contextlib.suppress(Exception):
                writer.close()

    async def _dispatch(self, peer: FederationPeer, frame: dict[str, Any]) -> None:
        t = frame.get("t")
        # Reject frames from a link that has been retired (e.g. a duplicate
        # connection for the same node that lost the dedup in _on_hello).
        if peer.node is not None and self._peers.get(peer.node) is not peer:
            return
        if t == "fed_hello":
            self._on_hello(peer, frame)
        elif t == "fed_spawn":
            self._register_remote_agent(peer, frame.get("agent") or {})
        elif t == "fed_despawn":
            self._unregister_remote_agent(peer, str(frame.get("agent_id") or ""))
        elif t == "fed_msg":
            await self._on_fed_msg(peer, frame)
        elif t == "fed_reply":
            self._on_fed_reply(peer, frame)

    # ── Handshake ─────────────────────────────────────────────────────────────

    def _on_hello(self, peer: FederationPeer, frame: dict[str, Any]) -> None:
        node = str(frame.get("node") or "")
        if not node:
            return
        # Never federate with ourselves (would mirror our own agents under node/id).
        if node == self.node_id:
            logger.warning("Refusing self-federation for node %s", node)
            with contextlib.suppress(Exception):
                peer.writer.close()
            return
        # Reconnect / duplicate: retire any stale link for the same node first.
        old = self._peers.get(node)
        if old is not None and old is not peer:
            self._cleanup_peer(old)
            with contextlib.suppress(Exception):
                old.writer.close()
        peer.node = node
        self._peers[node] = peer
        for info in frame.get("agents") or []:
            self._register_remote_agent(peer, info)

    # ── Consuming side: mirror remote agents as virtual sessions ──────────────

    def _register_remote_agent(self, peer: FederationPeer, info: dict[str, Any]) -> None:
        from mars.server.main import ClientSession, _agent_payload

        remote_id = str(info.get("agent_id") or "")
        if not remote_id or peer.node is None:
            return
        local_id = f"{peer.node}{FED_SEP}{remote_id}"
        srv = self._server
        # Never overwrite a real local session or an existing mirror.
        if local_id in srv._sessions_by_id or local_id in srv._state.agents:
            return
        agent_type = str(info.get("agent_type") or "Provider")
        writer = FederationWriter(
            lambda fr, rid=remote_id: self._forward_to_owner(peer, rid, fr)
        )
        sess = ClientSession(reader=None, writer=writer, addr=f"fed:{peer.node}", role="agent")
        sess.agent_id = local_id
        sess.agent_type = agent_type
        srv._sessions_by_id[local_id] = sess
        rec = AgentRecord(
            agent_id=local_id,
            agent_type=agent_type,
            domain="federated",
            platform=f"fed:{peer.node}",
            server_addr=peer.node,
            skills=list(info.get("skills") or []),
            model=str(info.get("model") or ""),
            vendor=str(info.get("vendor") or ""),
        )
        srv._state.agents[local_id] = rec
        peer.virtual_agents.add(local_id)
        srv._state._fire({"t": "spawn", "agent_id": local_id, **_agent_payload(rec, srv._state)})
        logger.info("Federated agent mirrored: %s (from %s)", local_id, peer.node)

    def _unregister_remote_agent(self, peer: FederationPeer, remote_id: str) -> None:
        if peer.node is None or not remote_id:
            return
        self._drop_virtual_agent(f"{peer.node}{FED_SEP}{remote_id}", peer)

    def _drop_virtual_agent(self, local_id: str, peer: FederationPeer) -> None:
        srv = self._server
        peer.virtual_agents.discard(local_id)
        srv._sessions_by_id.pop(local_id, None)
        if local_id in srv._state.agents:
            srv._state.agents.pop(local_id, None)
            srv._state._fire({"t": "despawn", "agent_id": local_id})

    def _forward_to_owner(
        self, peer: FederationPeer, remote_id: str, frame: dict[str, Any]
    ) -> None:
        """A frame the router delivered to a virtual agent → ship to its owner."""
        if frame.get("t") != "msg":
            return  # ignore room/status frames; rooms are out of scope for v1
        sender = str(frame.get("from") or "")
        text = str(frame.get("text") or "")
        msg_id = uuid.uuid4().hex
        peer.pending_out[msg_id] = sender
        self._send(peer.writer, {
            "t": "fed_msg", "msg_id": msg_id, "to": remote_id, "from": sender, "text": text,
        })

    # ── Owning side: route inbound fed_msg to the real local agent ────────────

    async def _on_fed_msg(self, peer: FederationPeer, frame: dict[str, Any]) -> None:
        from mars.server.main import ClientSession

        srv = self._server
        to = str(frame.get("to") or "")
        frm = str(frame.get("from") or "")
        text = str(frame.get("text") or "")
        msg_id = str(frame.get("msg_id") or "")
        if not to or peer.node is None:
            return

        target_rec = srv._state.agents.get(to)
        target_known = to in srv._sessions_by_id or to in srv._mcp_adapters
        # Refuse unknown targets and transitive federation (don't relay to another
        # node's mirrored agent) — both would otherwise hang or loop.
        if not target_known or (target_rec is not None and getattr(target_rec, "domain", "") == "federated"):
            self._send(peer.writer, {
                "t": "fed_reply", "msg_id": msg_id, "to": frm, "from": to,
                "text": f"(no local agent '{to}' on {self.node_id})",
            })
            return

        # One *unique* virtual caller per request: the real agent replies to this
        # caller id, so reply correlation is exact (no FIFO / ordering assumptions)
        # and survives concurrent / out-of-order replies from the same origin.
        caller_id = f"{peer.node}{FED_SEP}{frm}{FED_SEP}{msg_id}"
        writer = FederationWriter(
            lambda fr, cid=caller_id: self._owner_reply(peer, cid, fr)
        )
        caller = ClientSession(reader=None, writer=writer, addr=f"fed:{peer.node}", role="human")
        caller.name = caller_id
        caller.agent_id = caller_id
        srv._sessions_by_id[caller_id] = caller
        timer = asyncio.get_event_loop().call_later(
            FED_REQUEST_TIMEOUT, lambda cid=caller_id: self._expire_request(peer, cid)
        )
        peer.requests[caller_id] = {
            "msg_id": msg_id, "frm": frm, "to": to, "session": caller, "timer": timer,
        }
        await srv._route_message(caller, to, text)

    def _owner_reply(
        self, peer: FederationPeer, caller_id: str, frame: dict[str, Any]
    ) -> None:
        """A frame the router delivered to a virtual caller → ship back to origin.

        Only a *terminal* reply (``chat``/``msg``) completes a federated request;
        progress/``status`` frames are ignored so they cannot mis-consume request
        correlation. The first terminal frame finalises and reclaims the request.
        """
        if frame.get("t") not in ("chat", "msg"):
            return
        if caller_id not in peer.requests:
            return  # already finished (duplicate/late frame) — drop it
        text = str(frame.get("content") or frame.get("text") or "")
        from_agent = str(frame.get("agent_id") or frame.get("from") or "")
        self._finish_request(peer, caller_id, from_agent, text)

    def _finish_request(
        self, peer: FederationPeer, caller_id: str, from_agent: str, text: str
    ) -> None:
        req = peer.requests.pop(caller_id, None)
        if req is None:
            return
        timer = req.get("timer")
        if timer is not None:
            timer.cancel()
        self._server._sessions_by_id.pop(caller_id, None)
        self._send(peer.writer, {
            "t": "fed_reply", "msg_id": req["msg_id"], "to": req["frm"],
            "from": from_agent or req["to"], "text": text,
        })

    def _expire_request(self, peer: FederationPeer, caller_id: str) -> None:
        req = peer.requests.get(caller_id)
        if req is None:
            return
        self._finish_request(
            peer, caller_id, req["to"],
            f"(no reply from '{req['to']}' on {self.node_id} within {int(FED_REQUEST_TIMEOUT)}s)",
        )

    # ── Consuming side: deliver fed_reply to the original local sender ────────

    def _on_fed_reply(self, peer: FederationPeer, frame: dict[str, Any]) -> None:
        srv = self._server
        msg_id = str(frame.get("msg_id") or "")
        from_agent = str(frame.get("from") or "")
        text = str(frame.get("text") or "")
        sender_id = peer.pending_out.pop(msg_id, None) or str(frame.get("to") or "")
        target = srv._sessions_by_id.get(sender_id)
        if target is None:
            return
        local_fed_id = f"{peer.node}{FED_SEP}{from_agent}"
        now = datetime.now()
        if getattr(target, "role", "human") == "human":
            srv._send_to(target, {
                "t": "chat", "agent_id": local_fed_id, "sender": local_fed_id,
                "content": text, "direction": "in", "ts": now.isoformat(),
            })
            rec = srv._state.agents.get(local_fed_id)
            if rec is not None:
                rec.chat.append(ChatMessage(ts=now, sender=local_fed_id, content=text, direction="in"))
        else:
            with contextlib.suppress(Exception):
                target.writer.write(
                    encode_frame({"t": "msg", "from": local_fed_id, "text": text})
                )
        srv._record_feed(local_fed_id, sender_id, text[:80])

    # ── Local agent lifecycle → notify peers ──────────────────────────────────

    def broadcast_spawn(self, rec: AgentRecord) -> None:
        if getattr(rec, "domain", "") == "federated":
            return
        if getattr(rec, "agent_type", "") == "HumanUser":
            return
        info = self._agent_info(rec)
        for peer in list(self._peers.values()):
            self._send(peer.writer, {"t": "fed_spawn", "agent": info})

    def broadcast_despawn(self, agent_id: str) -> None:
        for peer in list(self._peers.values()):
            self._send(peer.writer, {"t": "fed_despawn", "agent_id": agent_id})

    # ── Teardown ──────────────────────────────────────────────────────────────

    def _cleanup_peer(self, peer: FederationPeer) -> None:
        srv = self._server
        for local_id in list(peer.virtual_agents):
            self._drop_virtual_agent(local_id, peer)
        for caller_id, req in list(peer.requests.items()):
            timer = req.get("timer")
            if timer is not None:
                timer.cancel()
            srv._sessions_by_id.pop(caller_id, None)
        peer.requests.clear()
        peer.pending_out.clear()
        if peer.node and self._peers.get(peer.node) is peer:
            self._peers.pop(peer.node, None)

    @property
    def peer_nodes(self) -> list[str]:
        return [n for n in self._peers]
