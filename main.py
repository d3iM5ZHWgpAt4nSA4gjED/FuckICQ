#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
枚举 flag.txt 每一行作为 answer，提交到 /match/red/submit。

签名算法（逆向自 match.ichunqiu.com 前端 index.c5d0d0cc.js 的 axios 拦截器）：
    rs   = MD5( (Date.now()+Math.random()) + "icq" )
    SIGN = MD5( sorted(["k=v", ...]) 拼接 "&" + "&7637b08bdb0b29e08300a976b24ca672" )
    参与签名的字段 = 最终请求体全部字段（k/stamp/token/rs/question_id/answer/img_url）
用法：
    python submit_enum.py --limit 3                # 先跑 3 条验证签名
    python submit_enum.py                          # 全量枚举
    python submit_enum.py --endpoint /match/red/submit_paper
"""
import argparse
import hashlib
import json
import os
import random
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from curl_cffi import requests

BASE = "https://apiterminator.ichunqiu.com"
SALT = "7637b08bdb0b29e08300a976b24ca672"
HERE = os.path.dirname(os.path.abspath(__file__))


def js_num_str(v):
    """模拟 JS Number.toString()：整数不带小数点，>=1e21 用科学计数法。"""
    if isinstance(v, int):
        return str(v)
    if v.is_integer() and abs(v) < 1e21:
        return str(int(v))
    return repr(v)


def js_str(v):
    """模拟 JS 模板字符串 `${v}`。"""
    if isinstance(v, bool):
        return "true" if v else "false"
    if v is None:
        return "null"
    if isinstance(v, (int, float)):
        return js_num_str(v)
    if isinstance(v, dict):
        return "[object Object]"
    if isinstance(v, list):
        return ",".join(js_str(x) for x in v)
    return str(v)


def md5(s):
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def make_rs(stamp):
    t = stamp + random.random()
    return md5(js_num_str(t) + "icq")


def make_sign(body):
    """SIGN = SHA1( sorted("k=v&...") + "&" + SALT )，与前端 yGe 一致。"""
    pairs = sorted(f"{k}={js_str(v)}" for k, v in body.items())
    return hashlib.sha1(("&".join(pairs) + "&" + SALT).encode("utf-8")).hexdigest()

def build(answer):
    body = {
        "answer": "flag{}",
        "img_url": "f97fae4e1ffdb1ee3b65231aa693ea85", # 无摄像头抓拍占位符
        "k": "", # 比赛 ID
        "question_id": "", # XXTEA 加密后的题目 ID
        "rs": "",
        "stamp": 0,
        "token": "login:match_:" # 登录 Session
    }
    body["answer"] = answer
    body["stamp"] = int(time.time() * 1000)
    body["rs"] = make_rs(body["stamp"])
    sign = make_sign(body)
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Connection": "keep-alive",
        #"Content-Length": "0",
        "Content-Type": "application/json",
        "Host": "apiterminator.ichunqiu.com",
        "Origin": "https://match.ichunqiu.com",
        "Referer": "https://match.ichunqiu.com/",
        "Sec-Ch-Ua": '"Not:A-Brand";v="8", "Chromium";v="156", "Google Chrome";v="156"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-site",
        "Sign": sign,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/156.0.0.0 Safari/537.36",
        "X-Lang": "zh-CN"
    }
    return body, headers


def submit(answer, endpoint):
    body, headers = build(answer)
    r = requests.post(BASE + endpoint, json=body, headers=headers,
                      impersonate="chrome", timeout=20)
    try:
        j = r.json()
    except Exception:
        j = {"_raw": r.text[:300]}
    return r.status_code, j, headers["Sign"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--flags", default=os.path.join(HERE, "flag.txt"))
    ap.add_argument("--endpoint", default="/match/red/submit")
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 条（0=全部）")
    ap.add_argument("--start", type=int, default=1, help="从第几条开始（1 起）")
    ap.add_argument("--delay", type=float, default=7.0, help="请求间隔（秒），服务端约 7s 滑动窗口限流")
    ap.add_argument("--rate-wait", type=float, default=3.0, help="触发限流后的基础冷却秒数（按重试次数递增）")
    ap.add_argument("--rate-retry", type=int, default=5, help="限流后同一条最多重试次数")
    args = ap.parse_args()

    with open(args.flags, "r", encoding="utf-8-sig") as f:
        flags = [ln.strip() for ln in f if ln.strip()]
    flags = flags[args.start - 1:]
    if args.limit:
        flags = flags[: args.limit]
    print(f"[*] 候选 {len(flags)} 条, endpoint={args.endpoint}")

    log_path = os.path.join(HERE, "submit_log.jsonl")
    next_slot = time.time()
    for n, fl in enumerate(flags, start=args.start):
        retry = 0
        while True:
            now = time.time()
            if now < next_slot:
                time.sleep(next_slot - now)
            next_slot = time.time() + args.delay

            try:
                status, j, sign = submit(fl, args.endpoint)
            except Exception as e:
                print(f"[{n}] {fl}  请求异常: {e!r}")
                retry += 1
                if retry > args.rate_retry:
                    break
                continue

            code = j.get("code")
            msg = j.get("msg") or j.get("message") or ""
            print(f"[{n}] {fl}  HTTP {status}  code={code}  msg={msg}")

            with open(log_path, "a", encoding="utf-8") as lg:
                lg.write(json.dumps({"n": n, "answer": fl, "http": status,
                                     "resp": j}, ensure_ascii=False) + "\n")

            if code == 0:
                print(f"\n[+] 命中：{fl}")
                print("    响应:", json.dumps(j, ensure_ascii=False))
                return

            if "频繁" in msg:
                retry += 1
                if retry > args.rate_retry:
                    print(f"  [!] 连续限流，跳过该条")
                    break
                # 服务端是滑动窗口限流：被拒也占窗口，需按窗口长度整体退避
                wait = args.rate_wait * retry
                print(f"  [~] 触发限流，冷却 {wait}s 后重试 ({retry}/{args.rate_retry})")
                time.sleep(wait)
                next_slot = time.time()
                continue
            break

    print("[*] 全部提交完毕，未命中，明细见 submit_log.jsonl")


if __name__ == "__main__":
    main()
