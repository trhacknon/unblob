"""
RAR Version 4.x
https://codedread.github.io/bitjs/docs/unrar.html

RAR Version 5.x
https://www.rarlab.com/technote.htm#rarsign
"""

from pathlib import Path
from typing import Optional

import rarfile
from structlog import get_logger

from unblob.extractors import Command

from ...models import ExtractError, File, Handler, HexString, ValidChunk

logger = get_logger()


def is_encrypted(path: Path):
    try:
        with rarfile.RarFile(path) as rar_file:
            return rar_file.needs_password()
    except (rarfile.Error, ValueError):
        return


class Extractor(Command):
    def extract(self, inpath: Path, outdir: Path):
        if is_encrypted(inpath):
            logger.warning(
                "Encrypted file is not extracted",
                path=inpath,
                chunk=self,
            )
            raise ExtractError()
        return super().extract(inpath, outdir)


class RarHandler(Handler):
    NAME = "rar"

    PATTERNS = [
        HexString(
            """
            // RAR v4.x ends with 00, RAR v5.x ends with 01 00
            52 61 72 21 1A 07 ( 00 | 01 00 )
        """
        )
    ]
    EXTRACTOR = Extractor(
        "unar", "-no-directory", "-p", "", "{inpath}", "-o", "{outdir}"
    )

    def calculate_chunk(self, file: File, start_offset: int) -> Optional[ValidChunk]:

        try:
            rar_file = rarfile.RarFile(file)
        except (rarfile.Error, ValueError):
            return

        # RarFile have the side effect of moving the file pointer
        rar_end_offset = file.tell()

        return ValidChunk(
            start_offset=start_offset,
            end_offset=rar_end_offset,
            is_encrypted=rar_file.needs_password(),
        )
