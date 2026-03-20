
import argparse
import asyncio
import json
import sys

from aiortc import RTCPeerConnection, RTCSessionDescription, RTCIceServer, RTCConfiguration


def make_pc():
    config = RTCConfiguration(
        iceServers=[
            RTCIceServer(urls=["stun:203.0.113.99:3478"]),
            RTCIceServer(
                urls=["turn:203.0.113.99:3478?transport=udp"],
                username="isep",
                credential="isep123",
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


async def run_offer():
    pc = make_pc()
    channel = pc.createDataChannel("chat")

    @channel.on("open")
    def on_open():
        print("[DATA] channel open")
        channel.send("Pergunte qualquer coisa");

    @channel.on("message")
    def on_message(message):
        print(f"< {message}")
        print("> ", end="", flush=True )
        msg_offer = sys.stdin.readline().strip()
        channel.send(msg_offer);

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

    print("Cole aqui a answer em JSON numa única linha:")
    answer_json = sys.stdin.readline().strip()
    answer = json.loads(answer_json)

    await pc.setRemoteDescription(
        RTCSessionDescription(sdp=answer["sdp"], type=answer["type"])
    )

    await asyncio.sleep(300)
    await pc.close()


async def run_answer():
    pc = make_pc()

    @pc.on("datachannel")
    def on_datachannel(channel):
        print(f"[DATA] channel recebido: {channel.label}")

        @channel.on("open")
        def on_open():
            print("[DATA] channel open")

        @channel.on("message")
        def on_message(message):
            print(f"< {message}")
            print("> ", end="", flush=True)
            msg_answer = sys.stdin.readline().strip()
            channel.send(msg_answer)

    print("Cole aqui a offer em JSON numa única linha:")
    offer_json = sys.stdin.readline().strip()
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

    await asyncio.sleep(300)
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
