import urllib.request, json, time
for i in range(8):
    try:
        req = urllib.request.Request(
            "http://127.0.0.1:8188/queue",
            data=json.dumps({"clear": "queue"}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        urllib.request.urlopen(req, timeout=15).read()
    except Exception as e:
        print("clear err", e)
    try:
        req = urllib.request.Request(
            "http://127.0.0.1:8188/interrupt",
            data=b"{}",
            headers={"Content-Type": "application/json"}, method="POST")
        urllib.request.urlopen(req, timeout=15).read()
    except Exception as e:
        print("int err", e)
    time.sleep(3)
    r = urllib.request.urlopen("http://127.0.0.1:8188/queue", timeout=15)
    d = json.loads(r.read())
    rn, pn = len(d["queue_running"]), len(d["queue_pending"])
    print(f"iter {i}: running={rn} pending={pn}")
    if rn == 0 and pn == 0:
        break
print("done")
