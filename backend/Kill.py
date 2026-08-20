"""Stop the uvicorn backend server running on port 8000."""
import subprocess
import sys


def stop_server(port: int = 8000):
    # Find PIDs listening on the target port
    result = subprocess.run(
        ["netstat", "-ano"],
        capture_output=True, text=True
    )
    pids = set()
    for line in result.stdout.splitlines():
        if f":{port}" in line and "LISTENING" in line:
            parts = line.split()
            if parts:
                pids.add(parts[-1])

    if not pids:
        print(f"No process found listening on port {port}.")
        return

    killed = 0
    for pid in pids:
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", pid],
                capture_output=True
            )
            print(f"Killed PID {pid}")
            killed += 1
        except Exception as e:
            print(f"Failed to kill PID {pid}: {e}")

    if killed:
        print(f"Server stopped ({killed} process(es) terminated).")
    else:
        print("Nothing was killed.")


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    stop_server(port)

 