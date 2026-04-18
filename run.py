import sys

if sys.platform.startswith("win"):
    import asyncio
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import uvicorn


def main():
    # 启动时携带 cookies 访问小红书，刷新 session 有效期
    from app.services.local_site_crawler_service import keepalive_xhs_session
    result = asyncio.run(keepalive_xhs_session())
    if result["success"]:
        print(f"[启动] {result['message']}")
    else:
        print(f"[启动] {result['message']}，不影响本次运行")

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    main()
