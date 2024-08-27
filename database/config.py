import os

import init


class Settings:
    db_host = os.getenv("db_host")
    db_port = os.getenv("db_port")
    db_user = os.getenv("db_user")
    db_pass = os.getenv("db_pass")
    db_name = os.getenv("db_name")

    @property
    def DB_URL_psycopg(self):
        print(
            f"postgresql+psycopg://{self.db_user}:{self.db_pass}@{self.db_host}:{self.db_port}/{self.db_name}"
        )
        return f"postgresql+psycopg://{self.db_user}:{self.db_pass}@{self.db_host}:{self.db_port}/{self.db_name}"


settings = Settings()
