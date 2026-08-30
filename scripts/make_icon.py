"""Generate the Narrative Workbench app icon (.icns)."""
from PIL import Image, ImageDraw
import os, subprocess, shutil

S = 1024
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

# rounded background with vertical gradient (deep green)
mask = Image.new("L", (S, S), 0)
ImageDraw.Draw(mask).rounded_rectangle([40, 40, S - 40, S - 40], radius=225, fill=255)
grad = Image.new("RGBA", (S, S))
top, bot = (74, 108, 96), (33, 56, 49)
for y in range(S):
    t = y / S
    for_x = tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3))
    ImageDraw.Draw(grad).line([(0, y), (S, y)], fill=for_x + (255,))
img.paste(grad, (0, 0), mask)

# paper
d.rounded_rectangle([215, 150, 705, 790], radius=40, fill=(246, 243, 236, 255),
                    outline=(220, 214, 202, 255), width=4)
# text lines
for i, (y, c) in enumerate([(250, (185, 178, 168)), (340, (185, 178, 168)),
                            (430, (185, 178, 168)), (520, (74, 128, 110)),
                            (610, (200, 194, 184))]):
    w = 340 if i % 2 == 0 else 270
    d.rounded_rectangle([280, y, 280 + w, y + 34], radius=17, fill=c)

# gold pen nib (diamond) bottom-right, with slit + breather hole
nib = [(720, 500), (842, 690), (720, 905), (598, 690)]
d.polygon(nib, fill=(226, 172, 74, 255))
d.polygon(nib, outline=(150, 105, 30, 255), width=0)
d.line([(745, 600), (690, 850)], fill=(58, 88, 78, 255), width=14)
d.ellipse([700, 655, 740, 695], fill=(58, 88, 78, 255))
# nib highlight
d.polygon([(720, 500), (775, 600), (720, 585), (672, 600)], fill=(245, 208, 130, 255))

set_dir = "AppIcon.iconset"
shutil.rmtree(set_dir, ignore_errors=True)
os.makedirs(set_dir)
for size, name in [(16, "icon_16x16.png"), (32, "icon_16x16@2x.png"),
                   (32, "icon_32x32.png"), (64, "icon_32x32@2x.png"),
                   (128, "icon_128x128.png"), (256, "icon_128x128@2x.png"),
                   (256, "icon_256x256.png"), (512, "icon_256x256@2x.png"),
                   (512, "icon_512x512.png"), (1024, "icon_512x512@2x.png")]:
    img.resize((size, size), Image.LANCZOS).save(f"{set_dir}/{name}")
subprocess.run(["iconutil", "-c", "icns", set_dir,
                "-o", "NarrativeWorkbench.app/Contents/Resources/AppIcon.icns"],
               check=True)
shutil.rmtree(set_dir)
print("AppIcon.icns written")
