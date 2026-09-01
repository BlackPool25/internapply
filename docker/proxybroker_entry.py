"""proxybroker2 entrypoint — runs proxy discovery server.

proxybroker2 2.x has a fundamental bug: Server.start() calls
loop.run_until_complete() which cannot be called from a running loop.
Workaround: monkey-patch start() to be awaitable instead.
"""
import asyncio
from proxybroker2 import Broker, Server


async def _patched_start(self):
    srv = asyncio.start_server(
        self._accept,
        host=self.host,
        port=self.port,
        backlog=self._backlog,
    )
    self._server = await srv
    print("proxybroker listening on {}:{}".format(self.host, self.port))


Server.start = _patched_start  # replace sync start with async version


async def main():
    broker = Broker(stop_broker_on_sigint=False)
    server = Server(host="0.0.0.0", port=8888, proxies=broker)
    asyncio.create_task(broker.find())
    await server.start()
    # keep running forever
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
