import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional, Any

import discord

logger = logging.getLogger(__name__)


@dataclass
class SendTask:
    channel_id: int
    content: Optional[str] = None
    embed: Optional[discord.Embed] = None
    view: Optional[discord.ui.View] = None
    allowed_mentions: Optional[discord.AllowedMentions] = None
    max_retries: int = 5
    delay_before_send: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


class MessageSenderQueue:
    def __init__(self, bot: discord.Client, base_interval: float = 1.2):
        self.bot = bot
        self.queue: asyncio.Queue[SendTask] = asyncio.Queue()
        self.base_interval = base_interval
        self.worker_task: Optional[asyncio.Task] = None
        self.running = False

    async def start(self):
        if self.running:
            return
        self.running = True
        self.worker_task = asyncio.create_task(self._worker_loop())
        logger.info("MessageSenderQueue worker started.")

    async def stop(self):
        self.running = False
        if self.worker_task:
            self.worker_task.cancel()
            try:
                await self.worker_task
            except asyncio.CancelledError:
                pass
        logger.info("MessageSenderQueue worker stopped.")

    async def enqueue(
        self,
        channel_id: int,
        content: Optional[str] = None,
        embed: Optional[discord.Embed] = None,
        view: Optional[discord.ui.View] = None,
        allowed_mentions: Optional[discord.AllowedMentions] = None,
        delay_before_send: float = 0.0,
        max_retries: int = 5,
        metadata: Optional[dict[str, Any]] = None,
    ):
        task = SendTask(
            channel_id=channel_id,
            content=content,
            embed=embed,
            view=view,
            allowed_mentions=allowed_mentions,
            max_retries=max_retries,
            delay_before_send=delay_before_send,
            metadata=metadata or {},
        )
        await self.queue.put(task)

    def qsize(self) -> int:
        return self.queue.qsize()

    async def _worker_loop(self):
        while self.running:
            task = await self.queue.get()
            try:
                if task.delay_before_send > 0:
                    await asyncio.sleep(task.delay_before_send)

                await self._send_with_retry(task)
                await asyncio.sleep(self.base_interval)

            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.exception(f"Unexpected error in send worker: {e}")
                await asyncio.sleep(3)
            finally:
                self.queue.task_done()

    async def _send_with_retry(self, task: SendTask):
        channel = self.bot.get_channel(task.channel_id)

        if channel is None:
            try:
                channel = await self.bot.fetch_channel(task.channel_id)
            except Exception as e:
                logger.warning(
                    f"Channel fetch failed: channel_id={task.channel_id}, error={e}"
                )
                return

        for attempt in range(task.max_retries + 1):
            try:
                await channel.send(
                    content=task.content,
                    embed=task.embed,
                    view=task.view,
                    allowed_mentions=task.allowed_mentions,
                )
                logger.info(
                    f"Message sent: channel_id={task.channel_id}, metadata={task.metadata}"
                )
                return

            except discord.HTTPException as e:
                status = getattr(e, "status", None)

                if status == 429:
                    retry_after = getattr(e, "retry_after", None)
                    if retry_after is None:
                        retry_after = 5

                    wait_time = float(retry_after) + 1.0
                    logger.warning(
                        f"Rate limited (429). Waiting {wait_time:.2f}s. "
                        f"channel_id={task.channel_id}, attempt={attempt + 1}"
                    )
                    await asyncio.sleep(wait_time)
                    continue

                if status in (500, 502, 503, 504) and attempt < task.max_retries:
                    wait_time = min(2 ** attempt, 30)
                    logger.warning(
                        f"Discord temporary error {status}. Retry in {wait_time}s. "
                        f"channel_id={task.channel_id}, attempt={attempt + 1}"
                    )
                    await asyncio.sleep(wait_time)
                    continue

                logger.exception(
                    f"HTTPException while sending: status={status}, "
                    f"channel_id={task.channel_id}, metadata={task.metadata}"
                )
                return

            except (discord.Forbidden, discord.NotFound) as e:
                logger.warning(
                    f"Cannot send message: channel_id={task.channel_id}, error={e}"
                )
                return

            except asyncio.TimeoutError:
                if attempt < task.max_retries:
                    wait_time = min(2 ** attempt, 30)
                    logger.warning(
                        f"Timeout while sending. Retry in {wait_time}s. "
                        f"channel_id={task.channel_id}, attempt={attempt + 1}"
                    )
                    await asyncio.sleep(wait_time)
                    continue

                logger.exception(
                    f"Timeout exceeded retries: channel_id={task.channel_id}, metadata={task.metadata}"
                )
                return

            except Exception as e:
                if attempt < task.max_retries:
                    wait_time = min(2 ** attempt, 30)
                    logger.warning(
                        f"Unexpected send error. Retry in {wait_time}s. "
                        f"channel_id={task.channel_id}, attempt={attempt + 1}, error={e}"
                    )
                    await asyncio.sleep(wait_time)
                    continue

                logger.exception(
                    f"Send failed after retries: channel_id={task.channel_id}, "
                    f"metadata={task.metadata}, error={e}"
                )
                return


async def enqueue_message(
    bot,
    channel_id: int,
    *,
    content: Optional[str] = None,
    embed: Optional[discord.Embed] = None,
    view: Optional[discord.ui.View] = None,
    allowed_mentions: Optional[discord.AllowedMentions] = None,
    delay_before_send: float = 0.0,
    metadata: Optional[dict[str, Any]] = None,
):
    if not hasattr(bot, "send_queue") or bot.send_queue is None:
        raise RuntimeError("send_queue is not initialized")

    await bot.send_queue.enqueue(
        channel_id=channel_id,
        content=content,
        embed=embed,
        view=view,
        allowed_mentions=allowed_mentions,
        delay_before_send=delay_before_send,
        metadata=metadata,
    )