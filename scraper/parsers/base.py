from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ParseResult:
    groups: list[dict]
    parser_used: str
    confidence: float  # 0.0–1.0
    warnings: list[str] = field(default_factory=list)
    raw_data: dict = field(default_factory=dict)


class BaseParser(ABC):
    def __init__(self, institute_config: dict):
        self.config = institute_config

    @abstractmethod
    def parse(self, source: str | bytes) -> ParseResult:
        """source — путь к файлу или URL"""
        ...

    def validate(self, result: ParseResult) -> bool:
        return len(result.groups) > 0 and result.confidence > 0.3
