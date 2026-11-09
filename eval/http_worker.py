"""One isolated HTTP operation. Parent owns the elapsed-time limit and kills this worker.

Requests (including credentials) travel over stdin, never argv or a temporary file.
This module is invoked only by providers._bounded_http; importing it makes no request.
"""
import json
import sys


def execute(request):
    import httpx

    method = request["method"]
    try:
        with httpx.stream("POST" if method == "stream" else method.upper(), request["url"],
                          headers=request["headers"], json=request.get("body"),
                          timeout=request["timeout"]) as response:
            data = bytearray()
            for chunk in response.iter_bytes():
                data.extend(chunk)
                if len(data) > 16 * 1024 * 1024:
                    return {"error": "Ambiguous", "detail": "response exceeds evidence size limit"}
            if method == "stream" and response.status_code == 200:
                payload = []
                for line in data.decode("utf-8").splitlines():
                    if line.startswith("data:") and line[5:].strip() != "[DONE]":
                        try:
                            payload.append(json.loads(line[5:]))
                        except ValueError:
                            payload.append({"unparsed": line[5:205]})
            else:
                try:
                    payload = json.loads(data)
                except ValueError:
                    payload = {"error": data[:400].decode("utf-8", errors="replace")}
                if method == "stream":
                    payload = [payload]
            return {"result": [response.status_code, dict(response.headers), payload]}
    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
        return {"error": "NotSent", "detail": "connection could not be established"}
    except Exception as error:
        # No traceback or credentials cross the boundary on failure.
        return {"error": "Ambiguous", "detail": type(error).__name__}


if __name__ == "__main__":
    request = json.loads(sys.stdin.buffer.read())
    sys.stdout.buffer.write(json.dumps(execute(request), ensure_ascii=True).encode("utf-8"))
