import argparse
import asyncio
import json
from aiortc import (
    RTCPeerConnection,
    RTCSessionDescription,
    RTCIceServer,
    RTCConfiguration,
)

TURN_USER = "isep"
TURN_PASS = "isep123"
TURN_HOST = "203.0.113.99"
TURN_PORT = 3478


def make_pc():
    config = RTCConfiguration(
        iceServers=[
            RTCIceServer(urls=[f"stun:{TURN_HOST}:{TURN_PORT}"]),
            RTCIceServer(
                urls=[f"turn:{TURN_HOST}:{TURN_PORT}?transport=udp"],
                username=TURN_USER,
                credential=TURN_PASS,
            ),
        ]
    )

    pc = RTCPeerConnection(configuration=config)

    @pc.on("iceconnectionstatechange")
    async def on_iceconnectionstatechange():
        print(f"[ICE] state = {pc.iceConnectionState}")

    @pc.on("connectionstatechange")
    async def on_connectionstatechange():
        print(f"[CONN] state = {pc.connectionState}")

    @pc.on("icegatheringstatechange")
    async def on_icegatheringstatechange():
        print(f"[ICE-GATHER] state = {pc.iceGatheringState}")

    return pc


async def ainput(prompt=""):
    return await asyncio.to_thread(input, prompt)


async def conversation_loop(channel, first_to_send: bool):
    """
    Funcionamento alternado:
    - quem começa com first_to_send=True envia primeiro;
    - depois espera;
    - ao receber, passa a poder enviar.
    """
    can_send = first_to_send
    inbox = asyncio.Queue()

    @channel.on("message")
    def on_message(message):
        inbox.put_nowait(str(message))

    while True:
        if can_send:
            msg = await ainput("> ")
            if msg.strip().lower() in {"sair", "exit", "quit"}:
                print("[APP] a terminar")
                await channel.close()
                break
            channel.send(msg)
            can_send = False
        else:
            print("[APP] à espera de mensagem...")
            msg = await inbox.get()
            print(f"< {msg}")
            can_send = True


async def run_offer():
    pc = make_pc()
    channel = pc.createDataChannel("chat")
    opened = asyncio.Event()

    @channel.on("open")
    def on_open():
        print("[DATA] channel open")
        opened.set()

    @channel.on("close")
    def on_close():
        print("[DATA] channel closed")

    offer = await pc.createOffer()
    await pc.setLocalDescription(offer)

    while pc.iceGatheringState != "complete":
        await asyncio.sleep(0.1)

    print("\n=== COPIAR ESTA OFFER PARA O OUTRO PEER ===")
    print(json.dumps({
        "sdp": pc.localDescription.sdp,
        "type": pc.localDescription.type,
    }))
    print("=== FIM OFFER ===\n")

    answer_json = input("Cole aqui a answer em JSON numa única linha:\n").strip()
    answer = json.loads(answer_json)

    await pc.setRemoteDescription(
        RTCSessionDescription(sdp=answer["sdp"], type=answer["type"])
    )

    await opened.wait()
    print("[APP] conversa iniciada; o OFFER envia primeiro")
    await conversation_loop(channel, first_to_send=True)

    await pc.close()


async def run_answer():
    pc = make_pc()
    channel_ready = asyncio.Queue()

    @pc.on("datachannel")
    def on_datachannel(channel):
        print(f"[DATA] channel recebido: {channel.label}")

        @channel.on("open")
        def on_open():
            print("[DATA] channel open")

        @channel.on("close")
        def on_close():
            print("[DATA] channel closed")

        channel_ready.put_nowait(channel)

    offer_json = input("Cole aqui a offer em JSON numa única linha:\n").strip()
    offer = json.loads(offer_json)

    await pc.setRemoteDescription(
        RTCSessionDescription(sdp=offer["sdp"], type=offer["type"])
    )

    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

    while pc.iceGatheringState != "complete":
        await asyncio.sleep(0.1)

    print("\n=== COPIAR ESTA ANSWER PARA O OUTRO PEER ===")
    print(json.dumps({
        "sdp": pc.localDescription.sdp,
        "type": pc.localDescription.type,
    }))
    print("=== FIM ANSWER ===\n")

    channel = await channel_ready.get()
    print("[APP] conversa iniciada; o ANSWER espera primeiro")
    await conversation_loop(channel, first_to_send=False)

    await pc.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("role", choices=["offer", "answer"])
    args = parser.parse_args()

    if args.role == "offer":
        asyncio.run(run_offer())
    else:
        asyncio.run(run_answer())


if __name__ == "__main__":
    main()

