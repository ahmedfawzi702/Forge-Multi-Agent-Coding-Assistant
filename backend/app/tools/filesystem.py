from app.execution.base import ExecutionEnvironment


class FileSystemTools:
    def __init__(self, environment: ExecutionEnvironment):
        self.environment = environment

    def read(self, path: str) -> str:
        return self.environment.read_file(path)
