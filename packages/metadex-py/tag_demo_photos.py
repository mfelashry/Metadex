"""Stamp demo EXIF onto the first 150 cat JPEGs without recompressing pixels."""

from pathlib import Path

import piexif

ROOT = Path("/Users/m/Documents/Metadex/cat-photos-350")
WHEN = b"2026:10:15 16:42:00"

LINES = [
    "Alex: Hey, are you still coming to the waterfront?",
    "Sam: Yes. I just left the apartment.",
    "Alex: Bring the photo from last Sunday.",
    "Sam: The one by the railing?",
    "Alex: That one. I want to compare the light.",
    "Sam: I have it on my phone.",
    "Alex: Meet me at the dock, not the cafe.",
    "Sam: Dock four, the wide one?",
    "Alex: Yes. The benches face the water.",
    "Sam: I can be there in twenty minutes.",
    "Alex: I will grab two coffees on the way.",
    "Sam: Oat milk for me, if they have it.",
    "Alex: Noted. I will text when I am close.",
    "Sam: The wind is up. I am bringing a jacket.",
    "Alex: Good. The photo looks colder than I remembered.",
    "Sam: Maybe it was just the evening.",
    "Alex: We can retake it if the light is better.",
    "Sam: Only if we are not in a rush.",
    "Alex: No rush. I cleared the afternoon.",
    "Sam: Then I will walk the long way along the path.",
    "Alex: Watch the bikes. They come fast there.",
    "Sam: I see them. I am at the crosswalk now.",
    "Alex: I am still in line for the coffee.",
    "Sam: Take your time. I can sit.",
    "Alex: There is a gull on the post again.",
    "Sam: Leave it. I want that in the next photo.",
    "Alex: I will not scare it off.",
    "Sam: Thank you. I am almost at the steps.",
    "Alex: I can see the masts from the shop window.",
    "Sam: The water is bright today.",
    "Alex: Better than Sunday. Less haze.",
    "Sam: I found the bench. Left side is free.",
    "Alex: Stay there. I am paying now.",
    "Sam: I put the photo on the bench so I do not forget.",
    "Alex: Do not let it blow away.",
    "Sam: I set my bag on the corner.",
    "Alex: Crossing the street. Two minutes.",
    "Sam: I hear the bell on the shop door.",
    "Alex: That was me. I am on the path.",
    "Sam: I see a person with two cups.",
    "Alex: Wave. I do not have a free hand.",
    "Sam: Waving. You can have the end of the bench.",
    "Alex: This coffee is hot. Give me a second.",
    "Sam: The photo is face down so the sun does not fade it.",
    "Alex: Smart. Let me look when I sit.",
    "Sam: Here. The railing is on the left.",
    "Alex: Yes. And the crane is tiny in the back.",
    "Sam: I like that. It says where we were.",
    "Alex: Should we stand in the same spot?",
    "Sam: The chalk mark is still on the board.",
    "Alex: I see it. Right by the cleat.",
    "Sam: I will hold the phone. You hold the print.",
    "Alex: Do not crop my shoes this time.",
    "Sam: I will step back. The dock is wide.",
    "Alex: A boat is coming in. Wait for the wake.",
    "Sam: It is a small one. We are fine.",
    "Alex: The light just moved off the cloud.",
    "Sam: Now. I am taking it.",
    "Alex: Did it blur?",
    "Sam: No. The railing is sharp.",
    "Alex: Let me see. Oh, that is better.",
    "Sam: Your collar is straight too.",
    "Alex: Send it to me before we leave.",
    "Sam: Sending. It may take a moment.",
    "Alex: Got it. The sky is cleaner.",
    "Sam: I like the old one as well.",
    "Alex: We can keep both. They are different hours.",
    "Sam: I will make a folder called waterfront.",
    "Alex: Put today's date on it.",
    "Sam: October fifteenth. Done.",
    "Alex: Want to walk to the end of the dock?",
    "Sam: Yes. My cup is almost empty.",
    "Alex: There is a painted fish on the last post.",
    "Sam: I missed that on Sunday.",
    "Alex: The paint is chipped, but the eye is still there.",
    "Sam: I will take one close photo of just the eye.",
    "Alex: No people in that one.",
    "Sam: Agreed. Just the post and the water.",
    "Alex: Hold the phone low so the planks lead in.",
    "Sam: Like this?",
    "Alex: Lower. Your shadow is in the corner.",
    "Sam: Moved. Shadow is gone.",
    "Alex: That frame is quiet. I like it.",
    "Sam: I will not add a filter.",
    "Alex: Please do not. The gray is the point.",
    "Sam: Saved as it is.",
    "Alex: A kid just ran past with a red kite.",
    "Sam: I did not catch it. The kite was too fast.",
    "Alex: That is all right. This trip was for the dock.",
    "Sam: Should we tell Jordan we found the bench?",
    "Alex: Send the wide photo, not our faces.",
    "Sam: I cropped it to the railing and the water.",
    "Alex: Perfect. Jordan only wanted the place.",
    "Sam: Sent. Jordan replied with a thumbs up.",
    "Alex: We can head back through the park.",
    "Sam: The long way, or the street?",
    "Alex: The park. The trees are turning.",
    "Sam: I have one more photo left on the roll I made.",
    "Alex: Use it on the first yellow tree.",
    "Sam: There. Second tree on the left.",
    "Alex: Nice. The path is empty behind it.",
    "Sam: I am glad we came back in the day.",
    "Alex: Me too. Sunday was only the idea.",
    "Sam: Next time we bring the tripod.",
    "Alex: Only if it fits in your bag.",
    "Sam: It folds. I checked this morning.",
    "Alex: Then yes. Same dock, earlier light.",
    "Sam: I can do Saturday if the weather holds.",
    "Alex: I will watch the forecast tonight.",
    "Sam: Text me if the wind is high.",
    "Alex: If it is high we stay at the bench.",
    "Sam: The bench was the best part anyway.",
    "Alex: And the coffee.",
    "Sam: And the coffee. Do not forget that.",
    "Alex: I wrote oat milk in my notes.",
    "Sam: You are very serious about coffee.",
    "Alex: Someone has to be.",
    "Sam: I am at the park gate now.",
    "Alex: I am a few steps behind you.",
    "Sam: I will wait by the map sign.",
    "Alex: I see you. Blue jacket.",
    "Sam: That is me. The photo folder is backed up.",
    "Alex: Good. I do not want to lose the railing one.",
    "Sam: It is the first image in the folder.",
    "Alex: I will look at it on a bigger screen tonight.",
    "Sam: Tell me if the horizon is tilted.",
    "Alex: It looks level to me.",
    "Sam: Then we did it right.",
    "Alex: Thank you for meeting me out here.",
    "Sam: Thank you for the coffee and the second try.",
    "Alex: Same time next clear day?",
    "Sam: Yes. Dock four, wide bench, no filter.",
    "Alex: I will bring the print again.",
    "Sam: I will bring the phone and the tripod.",
    "Alex: If it rains we just drink the coffee.",
    "Sam: Deal. The place will still be there.",
    "Alex: The map sign is easy to spot.",
    "Sam: I will not wander off.",
    "Alex: The print is back in the envelope.",
    "Sam: I zipped the folder so it stays together.",
    "Alex: Name the zip waterfront-oct-15.",
    "Sam: Named. Nothing private in the file names.",
    "Alex: I am home. The photos came through.",
    "Sam: Open the wide one first.",
    "Alex: The crane is small, like you said.",
    "Sam: And the gull stayed on the post.",
    "Alex: It did. I did not see it until now.",
    "Sam: That can be the quiet picture.",
    "Alex: I will not caption it. The dock is enough.",
    "Sam: Agreed. See you there. I will bring the photo.",
]


def exif_bytes(line: str) -> bytes:
    ascii_comment = b"ASCII\x00\x00\x00" + line.encode("ascii", "replace")
    payload = {
        "0th": {
            piexif.ImageIFD.Make: b"Canon",
            piexif.ImageIFD.Model: b"EOS R6",
            piexif.ImageIFD.Software: b"Metadex Demo",
            piexif.ImageIFD.DateTime: WHEN,
            piexif.ImageIFD.ImageDescription: line.encode("utf-8"),
        },
        "Exif": {
            piexif.ExifIFD.DateTimeOriginal: WHEN,
            piexif.ExifIFD.DateTimeDigitized: WHEN,
            piexif.ExifIFD.UserComment: ascii_comment,
        },
    }
    return piexif.dump(payload)


def main() -> None:
    files = sorted(ROOT.glob("*.jpg"))
    chosen = files[:150]
    if len(chosen) < 150:
        raise SystemExit(f"Need 150 jpegs, found {len(chosen)}")
    if len(LINES) < 150:
        raise SystemExit(f"Need 150 lines, found {len(LINES)}")
    for path, line in zip(chosen, LINES):
        piexif.insert(exif_bytes(line), str(path))
    print(f"tagged {len(chosen)}")
    print(chosen[0].name)
    print(LINES[0])
    print(chosen[-1].name)
    print(LINES[149])


if __name__ == "__main__":
    main()
