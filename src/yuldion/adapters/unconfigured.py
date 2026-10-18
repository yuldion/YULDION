from ..errors import YuldionError
from ..types import Health

class Unconfigured:
    def __init__(self, role):
        self.role = role
    def health(self):
        return Health(False, f"{self.role}: 모델 어댑터 미연결")
    def close(self):
        pass
    def __getattr__(self, name):
        raise YuldionError(f"{self.role} 어댑터를 연결해야 {name}을 실행할 수 있습니다.")
