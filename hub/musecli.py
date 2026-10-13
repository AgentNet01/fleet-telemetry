"""muse-cli, with one fix: muse.ai splits a large reply over several transport frames (chunk_id, chunk_index,
total_chunks), and muse-cli 0.3.x decodes each frame on its own — "Wire format was corrupt" on
egress.approvals and a long egress.approval.history. This joins the frames first, then runs muse-cli
unchanged. Drop it once muse-cli reassembles chunks itself.

    python musecli.py <any muse-cli arguments>
"""
from muse_cli import gateway as g


def _read_frame(self):
    parts = self.__dict__.setdefault("_parts", {})          # chunk_id -> {index: bytes}, kept across calls
    while True:
        with self._recv_lock:
            data, _flags = self.ws.recv()
            pt = bytes(self.noise.decrypt(bytes(data)))
        ntf = g.NoiseTransportFrame()
        ntf.ParseFromString(pt)
        if ntf.total_chunks <= 1:
            payload = ntf.payload
            break
        got = parts.setdefault(ntf.chunk_id, {})
        got[ntf.chunk_index] = ntf.payload
        if len(got) == ntf.total_chunks:
            payload = b"".join(got[i] for i in sorted(got))
            del parts[ntf.chunk_id]
            break
    sr = g.ServiceResponse()
    sr.ParseFromString(payload)
    sf = g.ServiceFrame()
    sf.ParseFromString(sr.payload)
    return sf


g.Gateway._read_frame = _read_frame

if __name__ == "__main__":
    from muse_cli.cli import main
    main()
