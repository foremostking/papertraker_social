"""
ScholarPilot VPN 自动管理工具
功能：
1. 检测 EasyConnect 进程和 VPN 隧道状态
2. 自动启动 EasyConnect（利用已保存的密码自动登录）
3. 启用自动登录配置
4. 等待 VPN 隧道建立
5. 提取 TWFID 供 API 访问使用
"""
import asyncio, httpx, hashlib, ssl, json, sqlite3, os, subprocess, time, binascii
from pathlib import Path

# ============ 配置 ============
EC_EXE = r"C:\Program Files (x86)\Sangfor\SSL\EasyConnect\EasyConnect.exe"
EC_AGENT_EXE = r"C:\Program Files (x86)\Sangfor\SSL\ECAgent\ECAgent.exe"
EC_DB_DIR = r"C:\Users\xuxiaobing\AppData\Roaming\Sangfor\SSL\ECAgent\s-1\default"
EC_MEM_DB = os.path.join(EC_DB_DIR, "p0", "mem.db")
VPN_URL = "https://vpn.lzufe.edu.cn:8444"
SALT = "__md5_salt_for_ecagent_session__"

# SSL 上下文（兼容 EasyConnect 自签名证书）
_SSL_CTX = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE
_SSL_CTX.set_ciphers("DEFAULT:@SECLEVEL=0")


class VPNManager:
    """EasyConnect VPN 自动管理器."""

    def __init__(self):
        self.twfid = None
        self.token = None
        self.ec_port = None

    # ============ 状态检测 ============

    def is_easyconnect_running(self) -> bool:
        """检查 EasyConnect 进程是否运行."""
        try:
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq EasyConnect.exe", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=5
            )
            return "EasyConnect.exe" in result.stdout
        except Exception:
            return False

    def is_ecagent_running(self) -> bool:
        """检查 ECAgent 进程是否运行."""
        try:
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq ECAgent.exe", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=5
            )
            return "ECAgent.exe" in result.stdout
        except Exception:
            return False

    def is_vpn_adapter_up(self) -> bool:
        """检查 Sangfor VPN 虚拟网卡是否启用."""
        try:
            result = subprocess.run(
                ["powershell", "-Command",
                 "Get-NetAdapter | Where-Object { $_.InterfaceDescription -like '*Sangfor*' } | Select-Object -ExpandProperty Status"],
                capture_output=True, text=True, timeout=5
            )
            return "Up" in result.stdout
        except Exception:
            return False

    def _load_credentials_from_db(self) -> bool:
        """从 ECAgent mem.db 加载 TWFID 和端口."""
        if not os.path.exists(EC_MEM_DB):
            return False
        try:
            conn = sqlite3.connect(EC_MEM_DB)
            cur = conn.cursor()
            tables = cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            for (tname,) in tables:
                rows = cur.execute(f'SELECT * FROM "{tname}"').fetchall()
                for key, value in rows:
                    if key == "twfID":
                        config = json.loads(value)
                        self.twfid = config.get("config", "").strip()
                    elif key == "token":
                        config = json.loads(value)
                        self.token = config.get("config", "").strip()
                    elif key == "sfjssdk":
                        config = json.loads(value)
                        self.ec_port = config.get("port", 54533)
            conn.close()
            if self.twfid:
                # 如果 token 没有从 DB 读到，用 TWFID + SALT 计算
                if not self.token:
                    self.token = hashlib.md5((self.twfid + SALT).encode()).hexdigest()
                return True
        except Exception as e:
            print(f"  [警告] 读取 ECAgent DB 失败: {e}")
        return False

    async def get_vpn_status(self) -> dict:
        """通过 ECAgent API 查询 VPN 登录状态."""
        if not self._load_credentials_from_db():
            return {"connected": False, "error": "无法加载 ECAgent 凭据"}

        ec_base = f"https://127.0.0.1:{self.ec_port or 54533}/ECAgent/"
        params = {
            "op": "DoQueryService",
            "arg1": "QUERY LOGINSTATUS",
            "type": "EC",
            "token": self.token,
        }
        try:
            async with httpx.AsyncClient(timeout=8, verify=_SSL_CTX, trust_env=False) as c:
                r = await c.get(ec_base, params=params)
                # 解析 JSONP 响应: ({...}) 或 cb_xxx({...})
                text = r.text.strip()
                if text.startswith("("):
                    text = text[1:]
                if text.endswith(");"):
                    text = text[:-2]
                # 处理可能的 callBack 前缀
                if "({" in text:
                    text = text[text.index("({") + 1:]
                if text.endswith(")"):
                    text = text[:-1]
                data = json.loads(text)
                status = data.get("data", {}).get("status", 0)
                return {
                    "connected": status == 1,
                    "status": status,
                    "raw": data,
                }
        except Exception as e:
            return {"connected": False, "error": str(e)}

    async def get_l3vpn_state(self) -> dict:
        """查询 L3VPN 隧道状态."""
        if not self.twfid:
            self._load_credentials_from_db()
        if not self.twfid:
            return {"error": "无 TWFID"}

        ec_base = f"https://127.0.0.1:{self.ec_port or 54533}/ECAgent/"
        params = {
            "op": "DoQueryService",
            "arg1": "QUERY QSTATE L3VPN",
            "type": "EC",
            "token": self.token,
        }
        try:
            async with httpx.AsyncClient(timeout=8, verify=_SSL_CTX, trust_env=False) as c:
                r = await c.get(ec_base, params=params)
                text = r.text.strip()
                # 解析嵌套 JSON
                if text.startswith("("):
                    text = text[1:]
                if text.endswith(");"):
                    text = text[:-2]
                data = json.loads(text)
                state_str = data.get("data", "")
                if isinstance(state_str, str):
                    # base=18&tcp=18&l3vpn=18
                    states = {}
                    for part in state_str.split("&"):
                        if "=" in part:
                            k, v = part.split("=", 1)
                            try:
                                states[k] = int(v)
                            except ValueError:
                                states[k] = v
                    return states
                return {"raw": state_str}
        except Exception as e:
            return {"error": str(e)}

    # ============ 自动登录配置 ============

    def enable_autologin(self) -> bool:
        """在 ECAgent mem.db 中启用自动登录（密码已保存时有效）."""
        if not os.path.exists(EC_MEM_DB):
            return False
        try:
            conn = sqlite3.connect(EC_MEM_DB)
            cur = conn.cursor()
            tables = cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            modified = False
            for (tname,) in tables:
                rows = cur.execute(f'SELECT * FROM "{tname}"').fetchall()
                for key, value in rows:
                    if key == "sfjssdklocal":
                        config = json.loads(value)
                        if config.get("enableAutoLogin") != 1:
                            config["enableAutoLogin"] = 1
                            cur.execute(
                                f'UPDATE "{tname}" SET VALUE = ? WHERE KEY = ?',
                                (json.dumps(config, ensure_ascii=False), key)
                            )
                            conn.commit()
                            modified = True
                            print(f"  [OK] enableAutoLogin: 0 -> 1")
                        else:
                            print(f"  [OK] enableAutoLogin 已为 1")
                        # 检查密码是否已保存
                        if config.get("enableSavePwd") == 1:
                            print(f"  [OK] enableSavePwd: 1 (密码已保存)")
                        else:
                            print(f"  [警告] enableSavePwd: 0 (密码未保存，自动登录可能失败)")
            conn.close()
            return modified or True
        except Exception as e:
            print(f"  [错误] 修改自动登录配置失败: {e}")
            return False

    # ============ 启动 EasyConnect ============

    def start_easyconnect(self) -> bool:
        """启动 EasyConnect 进程."""
        if self.is_easyconnect_running():
            print("  [OK] EasyConnect 已在运行")
            return True
        try:
            subprocess.Popen(
                [EC_EXE, "starttray"],
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            print(f"  [OK] 已启动 EasyConnect: {EC_EXE} starttray")
            return True
        except Exception as e:
            print(f"  [错误] 启动 EasyConnect 失败: {e}")
            return False

    # ============ 等待 VPN 连接 ============

    async def wait_for_connection(self, timeout: int = 60) -> bool:
        """等待 VPN 隧道建立."""
        print(f"  等待 VPN 隧道建立 (超时 {timeout}s)...")
        start = time.time()
        while time.time() - start < timeout:
            status = await self.get_vpn_status()
            if status.get("connected"):
                elapsed = int(time.time() - start)
                print(f"  [OK] VPN 已连接 ({elapsed}s)")
                return True
            await asyncio.sleep(2)
        print(f"  [超时] VPN 在 {timeout}s 内未连接")
        return False

    # ============ 完整自动化流程 ============

    async def ensure_connected(self) -> dict:
        """确保 VPN 隧道已连接，必要时自动启动和登录."""
        result = {
            "was_running": False,
            "was_connected": False,
            "started_ec": False,
            "enabled_autologin": False,
            "connected": False,
            "twfid": None,
            "error": None,
        }

        # Step 1: 检查当前状态
        print("=" * 50)
        print("VPN 自动连接流程")
        print("=" * 50)

        ec_running = self.is_easyconnect_running()
        result["was_running"] = ec_running
        print(f"\n1. EasyConnect 进程: {'运行中' if ec_running else '未运行'}")

        if ec_running:
            # 检查 VPN 隧道状态
            status = await self.get_vpn_status()
            if status.get("connected"):
                result["was_connected"] = True
                result["connected"] = True
                result["twfid"] = self.twfid
                print(f"   VPN 隧道: 已连接")
                print(f"   TWFID: {self.twfid}")
                l3vpn = await self.get_l3vpn_state()
                print(f"   L3VPN 状态: {l3vpn}")
                print("\n[完成] VPN 已连接，无需操作")
                return result
            else:
                print(f"   VPN 隧道: 未连接 (status={status.get('status')})")

        # Step 2: 启用自动登录
        print(f"\n2. 启用自动登录配置...")
        result["enabled_autologin"] = self.enable_autologin()

        # Step 3: 启动 EasyConnect（如果未运行）
        if not ec_running:
            print(f"\n3. 启动 EasyConnect...")
            result["started_ec"] = self.start_easyconnect()
            # 等待 ECAgent 启动
            print(f"   等待 ECAgent 服务启动...")
            await asyncio.sleep(5)
        else:
            print(f"\n3. EasyConnect 已运行，等待自动重连...")
            # EasyConnect 已运行但未连接，可能需要等待自动重连
            # 或重启 EasyConnect
            pass

        # Step 4: 等待 VPN 连接
        print(f"\n4. 等待 VPN 隧道建立...")
        connected = await self.wait_for_connection(timeout=60)
        result["connected"] = connected

        if connected:
            result["twfid"] = self.twfid
            print(f"   TWFID: {self.twfid}")
            l3vpn = await self.get_l3vpn_state()
            print(f"   L3VPN 状态: {l3vpn}")
            print("\n[完成] VPN 自动连接成功!")
        else:
            result["error"] = "VPN 自动连接失败，可能需要手动登录"
            print(f"\n[失败] VPN 未能在超时时间内连接")
            print(f"   可能原因: 密码未保存、会话过期、网络问题")
            print(f"   建议: 手动打开 EasyConnect 界面登录一次以保存密码")

        return result


async def main():
    """主函数：执行 VPN 自动连接流程."""
    mgr = VPNManager()
    result = await mgr.ensure_connected()
    print(f"\n{'=' * 50}")
    print("结果摘要:")
    for k, v in result.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    asyncio.run(main())
