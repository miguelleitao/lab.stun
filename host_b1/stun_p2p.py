
import argparse
import asyncio
import socket
import stun


def get_reflexive_address(stun_host, stun_port, local_ip, local_port):
    nat_type, external_ip, external_port = stun.get_ip_info(
        source_ip=local_ip,
        source_port=local_port,
        stun_host=stun_host,
        stun_port=stun_port,
    )
    return nat_type, external_ip, external_port


class PeerProtocol(asyncio.DatagramProtocol):
    def __init__(self):
        self.transport = None
        self.queue = asyncio.Queue()

    def connection_made(self, transport):
        self.transport = transport
        sock = transport.get_extra_info("socket")
        local = sock.getsockname()
        print(f"[LOCAL] escuta em {local[0]}:{local[1]}")

    def datagram_received(self, data, addr):
        msg = data.decode(errors="replace")
        print(f"\n< {addr[0]}:{addr[1]} :: {msg}")
        self.queue.put_nowait((msg, addr))

    def error_received(self, exc):
        print(f"[UDP-ERROR] {exc}")

    def connection_lost(self, exc):
        print("[UDP] socket fechado")


async def ainput(prompt=""):
    return await asyncio.to_thread(input, prompt)


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", choices=["A", "B"], required=True)
    parser.add_argument("--local-ip", default="0.0.0.0")
    parser.add_argument("--local-port", type=int, required=True)
    parser.add_argument("--stun-host", required=True)
    parser.add_argument("--stun-port", type=int, default=3478)
    args = parser.parse_args()

    print("[1] A obter endereço reflexivo via STUN...")
    nat_type, reflexive_ip, reflexive_port = get_reflexive_address(
        args.stun_host,
        args.stun_port,
        args.local_ip,
        args.local_port,
    )

    print(f"[STUN] NAT type: {nat_type}")
    print(f"[STUN] Reflexive address: {reflexive_ip}:{reflexive_port}")

    print("\n[2] Agora cria o socket UDP local no MESMO porto usado no STUN.")
    print("    Depois troca manualmente o reflexive address com o outro peer.\n")

    loop = asyncio.get_running_loop()
    protocol = PeerProtocol()

    transport, _ = await loop.create_datagram_endpoint(
        lambda: protocol,
        local_addr=(args.local_ip, args.local_port),
        family=socket.AF_INET,
    )

    try:
        other_ip = await ainput("Endereço reflexivo do outro peer - IP: ")
        other_port = int(await ainput("Endereço reflexivo do outro peer - porto: "))
        peer_addr = (other_ip.strip(), other_port)

        print(f"\n[3] Peer remoto configurado: {peer_addr[0]}:{peer_addr[1]}")

        print("[4] A enviar probes iniciais para abrir o NAT...")
        for i in range(10):
            msg = f"probe-{args.role}-{i}"
            transport.sendto(msg.encode(), peer_addr)
            await asyncio.sleep(0.5)

        print("[5] Probes enviados.")
        print("    Se o hole punching resultar, já deves começar a receber mensagens.")
        print("    Modo alternado: escreve uma linha, Enter, e espera resposta.")
        print("    'sair' para terminar.\n")

        if args.role == "A":
            can_send = True
        else:
            can_send = False

        while True:
            if can_send:
                msg = await ainput("> ")
                if msg.strip().lower() in {"sair", "exit", "quit"}:
                    break
                transport.sendto(msg.encode(), peer_addr)
                can_send = False
            else:
                print("[APP] à espera...")
                _, addr = await protocol.queue.get()
                peer_addr = addr
                can_send = True

    finally:
        transport.close()


if __name__ == "__main__":
    asyncio.run(main())

