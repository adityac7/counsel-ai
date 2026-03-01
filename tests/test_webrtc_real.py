import asyncio
import sys
import urllib.request
import urllib.error
from pathlib import Path

from aiortc import RTCPeerConnection

RTC_CONNECT_URL = "http://localhost:8501/api/rtc-connect"
SDP_PATH = Path("tests/real_offer.sdp")


async def build_offer() -> str:
    pc = RTCPeerConnection()
    pc.addTransceiver("audio", direction="sendrecv")
    offer = await pc.createOffer()
    try:
        await pc.setLocalDescription(offer)
        sdp = pc.localDescription.sdp
    except PermissionError as exc:
        print(f"ICE gather failed ({exc}); using raw offer SDP without candidates.")
        sdp = offer.sdp
    await pc.close()
    return sdp


def post_sdp(sdp: str):
    data = sdp.encode("utf-8")
    req = urllib.request.Request(
        RTC_CONNECT_URL,
        data=data,
        headers={"Content-Type": "application/sdp"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return resp.status, body
    except urllib.error.HTTPError as err:
        body = err.read().decode("utf-8", errors="replace")
        return err.code, body
    except urllib.error.URLError as err:
        return 0, f"URL error: {err}"


def main() -> int:
    sdp = asyncio.run(build_offer())
    SDP_PATH.write_text(sdp, encoding="utf-8")

    print("Generated SDP offer with audio:", "m=audio" in sdp)
    print(f"SDP saved to {SDP_PATH}")

    status, body = post_sdp(sdp)
    print(f"HTTP status: {status}")

    if status == 200:
        print("Received SDP answer.")
        print("Answer has audio m= line:", "m=audio" in body)
        return 0
    if status == 0:
        print(body)
        return 3

    if status == 400:
        print("400 error body from server/OpenAI:")
        print(body)
        return 1

    print("Unexpected response body:")
    print(body)
    return 2


if __name__ == "__main__":
    sys.exit(main())
