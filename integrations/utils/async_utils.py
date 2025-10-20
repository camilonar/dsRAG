import asyncio

import nest_asyncio


def sync(awaitable):
    loop = asyncio.get_event_loop()
    nest_asyncio.apply(loop)
    return loop.run_until_complete(awaitable)