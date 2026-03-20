import argparse
import asyncio
import ipaddress
import os
import random
import socket
import struct

MAGIC_COOKIE = 0x2112A442

BINDING_REQUEST = 0x0001
BINDING_RESPONSE = 0x0101
BINDING_ERROR_RESPONSE = 0x0111

ATTR_MAPPED_ADDRESS = 0x0001
ATTR_XOR_MAPPED_ADDRESS = 0x0020
ATTR_ERROR_CODE = 0x0009
ATTR_SOFTWARE = 0x8022


def build_binding_request():
    txid = os.urandom(12)
    msg_type = BINDING_REQUEST
    msg_len = 0
    header = struct.pack("!HHI12s", msg_type, msg_len, MAGIC_COOKIE, txid)
    return header, txid


def parse_stun_message(data, expected_txid):
    if len(data) < 20:
        raise ValueError("mensagem STUN demasiado curta")

    msg_type, msg_len, magic_cookie = struct.unpack("!HHI", data[:8])
    txid = data[8:20]

    if magic_cookie != MAGIC_COOKIE:
        raise ValueError("magic cookie inválido")

    if txid != expected_txid:
        raise ValueError("transaction ID não corresponde")

    if len(data) < 20 + msg_len:
        raise ValueError("mensagem STUN truncada")

    attrs = data[20:20 + msg_len]
    pos = 0
    result = {
        "msg_type": msg_type,
        "xor_mapped_address": None,
        "mapped_address": None,
        "error": None,
        "software": None,
    }

    while pos + 4 <= len(attrs):
        attr_type, attr_len = struct.unpack("!HH", attrs[pos:pos + 4])
        start = pos + 4
        end = start + attr_len
        if end > len(attrs):
            raise ValueError("atributo STUN truncado")

        value = attrs[start:end]

        if attr_type == ATTR_XOR_MAPPED_ADDRESS:
            result["xor_mapped_address"] = parse_xor_mapped_address(value, txid)
        elif attr_type == ATTR_MAPPED_ADDRESS:
            result["mapped_address"] = parse_mapped_address(value)
        elif attr_type == ATTR_ERROR_CODE:
            result["error"] = parse_error_code(value)
        elif attr_type == ATTR_SOFTWARE:
            try:
                result["software"] = value.decode("utf-8", errors="replace")
            except Exception:
                result["software"] = repr(value)

        padded_len = (attr_len + 3) & ~3
        pos += 4 + padded_len

    return result


def parse_mapped_address(value):
    if len(value) < 4:
        raise ValueError("MAPPED-ADDRESS inválido")

    _zero = value[0]
    family = value[1]
    port = struct.unpack("!H", value[2:4])[0]

    if family == 0x01:
        if len(value) < 8:
            raise ValueError("MAPPED-ADDRESS IPv4 inválido")
        ip = socket.inet_ntoa(value[4:8])
        return ip, port

    raise ValueError("família não suportada em MAPPED-ADDRESS")


def parse_xor_mapped_address(value, txid):
    if len(value) < 4:
        raise ValueError("XOR-MAPPED-ADDRESS inválido")

    _zero = value[0]
    family = value[1]
    xport = struct.unpack("!H", value[2:4])[0]
    port = xport ^ (MAGIC_COOKIE >> 16)

    if family == 0x01:
        if len(value) < 8:
            raise ValueError("XOR-MAPPED-ADDRESS IPv4 inválido")
        cookie_bytes = struct.pack("!I", MAGIC_COOKIE)
        raw_ip = bytes(a ^ b for a, b in zip(value[4:8], cookie_bytes))
        ip = socket.inet_ntoa(raw_ip)
        return ip, port

    elif family == 0x02:
        if len(value) < 20:
            raise ValueError("XOR-MAPPED-ADDRESS IPv6 inválido")
        xpad = struct.pack("!I", MAGIC_COOKIE) + txid
        raw_ip = bytes(a ^ b for a, b in zip(value[4:20], xpad))
        ip = socket.inet_ntop(socket.AF_INET6, raw_ip)
        return ip, port

    raise ValueError("família não suportada em XOR-MAPPED-ADDRESS")


def parse_error_code(value):
    if len(value) < 4:
        return "erro STUN desconhecido"

    error_class = value[2] & 0x07
    error_number = value[3]
    code = error_class * 100 + error_number
    reason = value[4:].decode("utf-8", errors="replace") if len(value) > 4 else ""
    return f"{code} {reason}".strip()


async def stun_query(sock, stun_host, stun_port, timeout=3.0):
    request, txid = build_binding_request()
    loop = asyncio.get_running_loop()

    await loop.sock_sendto(sock, request, (stun_host, stun_port))

    try:
        data, addr = await asyncio.wait_for(loop.sock_recvfrom(sock, 2048), timeout=timeout)
    except asyncio.TimeoutError:
        raise TimeoutError("timeout à espera da resposta STUN")

    resp = parse_stun_message(data, txid)

    if resp["msg_type"] == BINDING_ERROR_RESPONSE:
        raise RuntimeError(f"servidor STUN respondeu com erro: {resp['error']}")

    if resp["msg_type"] != BINDING_RESPONSE:
        raise RuntimeError(f"resposta STUN inesperada: tipo 0x{resp['msg_type']:04x}")

    reflexive = resp["xor_mapped_address"] or resp["mapped_address"]
    if not reflexive:
        raise RuntimeError("resposta STUN sem MAPPED-ADDRESS/XOR-MAPPED-ADDRESS")

    return {
        "server_addr": addr,
        "reflexive_addr": reflexive,
        "software": resp["software"],
    }


def parse_peer_addr(text):
    text = text.strip()
    if ":" not in text:
        raise ValueError("formato esperado: IP:PORTO")

    ip_part, port_part = text.rsplit(":", 1)
    ipaddress.ip_address(ip_part)
    port = int(port_part)
    if not (1 <= port <= 65535):
        raise ValueError("porto inválido")

    return ip_part, port


async def ainput(prompt=""):
    return await asyncio.to_thread(input, prompt)


async def recv_until_peer(sock, expected_peer=None, ignore_addr=None):
    loop = asyncio.get_running_loop()

    while True:
        data, addr = await loop.sock_recvfrom(sock, 2048)

        if ignore_addr is not None and addr == ignore_addr:
            continue

        msg = data.decode("utf-8", errors="replace")

        if expected_peer is None or addr == expected_peer:
            return msg, addr

        print(f"[IGNORADO] recebido de {addr[0]}:{addr[1]} -> {msg}")


async def send_probes(sock, peer_addr, count=10, interval=0.5):
    loop = asyncio.get_running_loop()
    for i in range(count):
        msg = f"probe-{i}"
        await loop.sock_sendto(sock, msg.encode(), peer_addr)
        print(f"[PROBE] enviado para {peer_addr[0]}:{peer_addr[1]} -> {msg}")
        await asyncio.sleep(interval)


async def alternating_chat(sock, my_role, peer_addr, stun_server_addr):
    loop = asyncio.get_running_loop()

    if my_role == "A":
        can_send = True
    else:
        can_send = False

    print("\n[CHAT] modo alternado")
    print("[CHAT] escreve uma linha e Enter")
    print("[CHAT] termina com: sair\n")

    while True:
        if can_send:
            line = await ainput("> ")
            if line.strip().lower() in {"sair", "exit", "quit"}:
                await loop.sock_sendto(sock, line.encode(), peer_addr)
                print("[CHAT] terminado localmente")
                break

            await loop.sock_sendto(sock, line.encode(), peer_addr)
            can_send = False
        else:
            print("[CHAT] à espera...")
            msg, addr = await recv_until_peer(
                sock,
                expected_peer=peer_addr,
                ignore_addr=stun_server_addr,
            )
            print(f"< {msg}")

            if msg.strip().lower() in {"sair", "exit", "quit"}:
                print("[CHAT] peer terminou a sessão")
                break

            can_send = True


async def main():
    parser = argparse.ArgumentParser(description="Demo STUN + UDP hole punching sem dependências")
    parser.add_argument("--role", choices=["A", "B"], required=True, help="A envia primeiro, B recebe primeiro")
    parser.add_argument("--local-ip", default="0.0.0.0", help="IP local a usar")
    parser.add_argument("--local-port", type=int, required=True, help="porto UDP local fixo")
    parser.add_argument("--stun-host", required=True, help="IP ou hostname do servidor STUN")
    parser.add_argument("--stun-port", type=int, default=3478, help="porto do servidor STUN")
    args = parser.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setblocking(False)
    sock.bind((args.local_ip, args.local_port))

    try:
        local_addr = sock.getsockname()
        print(f"[LOCAL] socket UDP aberto em {local_addr[0]}:{local_addr[1]}")

        print("[STUN] a obter endereço reflexivo...")
        stun_info = await stun_query(sock, args.stun_host, args.stun_port)
        reflexive_ip, reflexive_port = stun_info["reflexive_addr"]

        print(f"[STUN] servidor respondeu de {stun_info['server_addr'][0]}:{stun_info['server_addr'][1]}")
        if stun_info["software"]:
            print(f"[STUN] software: {stun_info['software']}")
        print(f"[STUN] endereço reflexivo: {reflexive_ip}:{reflexive_port}")

        print("\nTroca este endereço com o outro peer.")
        print("Quando tiveres o do outro lado, introduz no formato IP:PORTO.\n")

        peer_text = await ainput("Reflexivo do outro peer: ")
        peer_addr = parse_peer_addr(peer_text)

        print(f"\n[PEER] peer remoto: {peer_addr[0]}:{peer_addr[1]}")
        print("[PUNCH] a enviar probes iniciais...")

        await send_probes(sock, peer_addr, count=10, interval=0.5)

        print("[PUNCH] probes enviados.")
        print("[PUNCH] se o NAT permitir UDP hole punching, a comunicação direta deve funcionar.\n")

        await alternating_chat(sock, args.role, peer_addr, stun_info["server_addr"])

    finally:
        sock.close()


if __name__ == "__main__":
    asyncio.run(main())

