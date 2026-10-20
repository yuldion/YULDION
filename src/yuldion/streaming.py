"""Bounded face consumer: audio producers never wait on face rendering.

A saturated visual queue drops whole face requests, with an explicit event.
PCM and its sample clock are never dropped, stretched or rewritten here.
"""
from queue import Queue,Empty,Full
from threading import Thread,Event
import time
from .errors import Cancelled


class FaceConsumer:
    def __init__(self,consume,cancel,on_drop,capacity=32):
        if type(capacity) is not int or capacity<1:raise ValueError('Positive face queue capacity required')
        self.queue=Queue(capacity);self.consume=consume;self.cancel=cancel;self.on_drop=on_drop
        self.stop=Event();self.error=None;self.completed=0;self.dropped=0
        self.thread=Thread(target=self._run,daemon=True,name='yuldion-face-consumer');self.thread.start()
    def _run(self):
        while not self.stop.is_set():
            try:task=self.queue.get(timeout=.05)
            except Empty:continue
            try:
                if not self.cancel.is_set() and not self.stop.is_set():
                    self.consume(task,self.stop);self.completed+=1
            except Exception as error:self.error=error;self.stop.set()
            finally:self.queue.task_done()
    def submit(self,task):
        if self.error:return
        if self.stop.is_set() or self.cancel.is_set():return
        try:self.queue.put_nowait(task)
        except Full:self.dropped+=1;self.on_drop(task)
    def finish(self,deadline):
        while self.queue.unfinished_tasks and not self.error:
            if self.cancel.is_set() or time.monotonic()>=deadline:raise Cancelled('Face drain cancelled or timed out')
            time.sleep(.005)
        if self.error:raise self.error
    def close(self):
        self.stop.set();self.thread.join(timeout=.1)
