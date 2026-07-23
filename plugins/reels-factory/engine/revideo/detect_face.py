import cv2, subprocess, json, os, sys

VID = "public/base.mp4"
TMP = "public/_faceframe.jpg"

# grab a mid frame where the face is clearly visible
subprocess.run(["ffmpeg","-y","-ss","9.0","-i",VID,"-frames:v","1","-q:v","2",TMP],
               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

img = cv2.imread(TMP)
H, W = img.shape[:2]
gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")

# sample a few timestamps and average, for robustness
xs, ys, ws, hs = [], [], [], []
for ts in [8.6, 9.0, 9.5, 10.2, 24.0]:
    subprocess.run(["ffmpeg","-y","-ss",str(ts),"-i",VID,"-frames:v","1","-q:v","2",TMP],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    im = cv2.imread(TMP)
    g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
    faces = cascade.detectMultiScale(g, 1.1, 6, minSize=(120,120))
    if len(faces):
        x,y,w,h = sorted(faces, key=lambda f: f[2]*f[3])[-1]
        xs.append(x+w/2); ys.append(y+h/2); ws.append(w); hs.append(h)

if not xs:
    print(json.dumps({"ok": False}))
    sys.exit(0)

fx = sum(xs)/len(xs)
fy = sum(ys)/len(ys)
fw = sum(ws)/len(ws)
fh = sum(hs)/len(hs)
# shift focus point a touch up toward eyes for nicer framing
fy = fy - fh*0.10

if os.path.exists(TMP): os.remove(TMP)
print(json.dumps({"ok": True, "W": W, "H": H, "face_cx": round(fx,1),
                  "face_cy": round(fy,1), "face_w": round(fw,1), "face_h": round(fh,1),
                  "samples": len(xs)}))
