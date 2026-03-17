"""
airsim_process.py
在独立子进程里运行 airsim client，避免 tornado/gevent event loop 冲突。
主进程通过 multiprocessing.Queue 发指令，子进程执行后返回结果。
"""
import multiprocessing as mp
import time
import traceback


def _worker(req_q: mp.Queue, res_q: mp.Queue, ip: str, port: int, vehicle: str):
    """子进程入口：独立的 tornado ioloop，不受 flask/gevent 影响。"""
    try:
        import airsim
        client = airsim.MultirotorClient(ip=ip, port=port, timeout_value=10)
        client.confirmConnection()
        client.enableApiControl(True, vehicle_name=vehicle)
        res_q.put({"ok": True, "msg": f"Connected to AirSim {ip}:{port}"})
    except Exception as e:
        res_q.put({"ok": False, "msg": str(e)})
        return

    while True:
        try:
            cmd = req_q.get(timeout=30)
        except Exception:
            continue

        if cmd is None:  # shutdown
            break

        action = cmd.get("action")
        try:
            if action == "get_state":
                state = client.getMultirotorState(vehicle_name=vehicle)
                pos = state.kinematics_estimated.position
                vel = state.kinematics_estimated.linear_velocity
                res_q.put({"ok": True, "data": {
                    "x": pos.x_val, "y": pos.y_val, "z": pos.z_val,
                    "vx": vel.x_val, "vy": vel.y_val, "vz": vel.z_val,
                    "landed": state.landed_state,
                }})
            elif action == "takeoff":
                alt = cmd.get("alt", 3.0)
                client.takeoffAsync(altitude=alt, vehicle_name=vehicle).join()
                res_q.put({"ok": True})
            elif action == "land":
                client.landAsync(vehicle_name=vehicle).join()
                res_q.put({"ok": True})
            elif action == "move_to":
                x, y, z = cmd["x"], cmd["y"], cmd["z"]
                speed = cmd.get("speed", 5.0)
                client.moveToPositionAsync(x, y, z, speed, vehicle_name=vehicle).join()
                res_q.put({"ok": True})
            elif action == "hover":
                client.hoverAsync(vehicle_name=vehicle).join()
                res_q.put({"ok": True})
            elif action == "get_image":
                import numpy as np
                import base64, cv2
                responses = client.simGetImages([
                    airsim.ImageRequest("0", airsim.ImageType.Scene, False, False)
                ], vehicle_name=vehicle)
                if responses:
                    img1d = np.frombuffer(responses[0].image_data_uint8, dtype=np.uint8)
                    img = img1d.reshape(responses[0].height, responses[0].width, 3)
                    _, buf = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, 70])
                    b64 = base64.b64encode(buf).decode()
                    res_q.put({"ok": True, "data": b64})
                else:
                    res_q.put({"ok": False, "msg": "no image"})
            elif action == "ping":
                res_q.put({"ok": True})
            else:
                res_q.put({"ok": False, "msg": f"unknown action: {action}"})
        except Exception as e:
            res_q.put({"ok": False, "msg": str(e), "trace": traceback.format_exc()})


class AirSimProcess:
    """主进程侧的代理，通过队列控制子进程里的 airsim client。"""

    def __init__(self, ip="127.0.0.1", port=41451, vehicle=""):
        self._ip = ip
        self._port = port
        self._vehicle = vehicle
        self._proc = None
        self._req_q = None
        self._res_q = None

    def connect(self, timeout=20) -> bool:
        self._req_q = mp.Queue()
        self._res_q = mp.Queue()
        self._proc = mp.Process(
            target=_worker,
            args=(self._req_q, self._res_q, self._ip, self._port, self._vehicle),
            daemon=True,
        )
        self._proc.start()
        try:
            result = self._res_q.get(timeout=timeout)
            return result.get("ok", False)
        except Exception as e:
            return False

    def call(self, action: str, timeout=15, **kwargs) -> dict:
        if not self._proc or not self._proc.is_alive():
            return {"ok": False, "msg": "process not running"}
        self._req_q.put({"action": action, **kwargs})
        try:
            return self._res_q.get(timeout=timeout)
        except Exception:
            return {"ok": False, "msg": "timeout"}

    def disconnect(self):
        if self._proc:
            try:
                self._req_q.put(None)
                self._proc.join(timeout=3)
            except Exception:
                pass
            if self._proc.is_alive():
                self._proc.terminate()
