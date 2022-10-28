import io
import struct
from pathlib import Path
from typing import Optional

from dissect.cstruct import Instance
from structlog import get_logger

from ...extractors import Command
from ...file_utils import InvalidInputFormat, iterate_patterns
from ...models import ExtractError, File, HexString, StructHandler, ValidChunk

logger = get_logger()

ENCRYPTED_FLAG = 0b0001
EOCD_RECORD_HEADER = 0x6054B50
ZIP64_EOCD_SIGNATURE = 0x06064B50
ZIP64_EOCD_LOCATOR_HEADER = 0x07064B50


def is_encrypted(path: Path):
    # This is only a PoC.
    # proper implementation would require extracting
    # encryption detection functionality from ZIPHandler
    with File.from_path(path) as file:
        chunk = ZIPHandler().calculate_chunk(file, 0)
    if chunk:
        return chunk.is_encrypted


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


class ZIPHandler(StructHandler):
    NAME = "zip"

    PATTERNS = [HexString("50 4B 03 04 // Local file header only")]
    C_DEFINITIONS = r"""

        typedef struct cd_file_header {
            uint32 magic;
            uint16 version_made_by;
            uint16 version_needed;
            uint16 flags;
            uint16 compression_method;
            uint16 dostime;
            uint16 dosdate;
            uint32 crc32_cs;
            uint32 compress_size;
            uint32 file_size;
            uint16 file_name_length;
            uint16 extra_field_length;
            uint16 file_comment_length;
            uint16 disk_number_start;
            uint16 internal_file_attr;
            uint32 external_file_attr;
            uint32 relative_offset_local_header;
            char file_name[file_name_length];
            char extra_field[extra_field_length];
        } cd_file_header_t;

        typedef struct end_of_central_directory
        {
            uint32 end_of_central_signature;
            uint16 disk_number;
            uint16 disk_number_with_cd;
            uint16 disk_entries;
            uint16 total_entries;
            uint32 central_directory_size;
            uint32 offset_of_cd;
            uint16 comment_len;
            char zip_file_comment[comment_len];
        } end_of_central_directory_t;

        typedef struct zip64_end_of_central_directory_locator
        {
            uint32 signature;
            uint32 disk_number;
            uint64 offset_of_cd;
            uint32 total_disk;
        } zip64_end_of_central_directory_locator_t;

        typedef struct zip64_end_of_central_directory
        {
            uint32 signature;
            uint64 size_of_eocd_record;
            uint16 version_made_by;
            uint16 version_needed;
            uint32 disk_number;
            uint32 disk_number_with_cd;
            uint64 total_entries_disk;
            uint64 total_entries;
            uint64 size_of_cd;
            uint64 offset_of_cd;
        } zip64_end_of_central_directory_t;

    """
    HEADER_STRUCT = "end_of_central_directory_t"

    # empty password with -p will make sure the command will not hang
    EXTRACTOR = Extractor("7z", "x", "-p", "-y", "{inpath}", "-o{outdir}")

    def has_encrypted_files(
        self,
        file: File,
        start_offset: int,
        end_of_central_directory: Instance,
    ) -> bool:
        file.seek(start_offset + end_of_central_directory.offset_of_cd, io.SEEK_SET)
        for _ in range(0, end_of_central_directory.total_entries):
            cd_header = self.cparser_le.cd_file_header_t(file)
            if cd_header.flags & ENCRYPTED_FLAG:
                return True
        return False

    @staticmethod
    def is_zip64_eocd(end_of_central_directory: Instance):
        # see https://pkware.cachefly.net/webdocs/APPNOTE/APPNOTE-6.3.1.TXT section J
        return (
            end_of_central_directory.disk_number == 0xFFFF
            or end_of_central_directory.disk_number_with_cd == 0xFFFF
            or end_of_central_directory.disk_entries == 0xFFFF
            or end_of_central_directory.total_entries == 0xFFFF
            or end_of_central_directory.central_directory_size == 0xFFFFFFFF
            or end_of_central_directory.offset_of_cd == 0xFFFFFFFF
        )

    def _parse_zip64(self, file: File, start_offset: int, offset: int) -> Instance:
        file.seek(start_offset, io.SEEK_SET)
        for eocd_locator_offset in iterate_patterns(
            file, struct.pack("<I", ZIP64_EOCD_LOCATOR_HEADER)
        ):
            file.seek(eocd_locator_offset, io.SEEK_SET)
            eocd_locator = self.cparser_le.zip64_end_of_central_directory_locator_t(
                file
            )
            logger.debug("eocd_locator", eocd_locator=eocd_locator, _verbosity=3)

            # ZIP64 EOCD locator is right before the EOCD record
            if eocd_locator_offset + len(eocd_locator) == offset:
                file.seek(start_offset + eocd_locator.offset_of_cd)
                zip64_eocd = self.cparser_le.zip64_end_of_central_directory_t(file)
                logger.debug("zip64_eocd", zip64_eocd=zip64_eocd, _verbosity=3)

                if zip64_eocd.signature != ZIP64_EOCD_SIGNATURE:
                    raise InvalidInputFormat(
                        "Missing ZIP64 EOCD header record header in ZIP chunk."
                    )
                return zip64_eocd
        raise InvalidInputFormat(
            "Missing ZIP64 EOCD locator record header in ZIP chunk."
        )

    def calculate_chunk(self, file: File, start_offset: int) -> Optional[ValidChunk]:

        has_encrypted_files = False
        file.seek(start_offset, io.SEEK_SET)

        for offset in iterate_patterns(file, struct.pack("<I", EOCD_RECORD_HEADER)):
            file.seek(offset, io.SEEK_SET)
            end_of_central_directory = self.parse_header(file)

            if self.is_zip64_eocd(end_of_central_directory):
                end_of_central_directory = self._parse_zip64(file, start_offset, offset)
                break
            else:
                # the EOCD offset is equal to the offset of CD + size of CD
                end_of_central_directory_offset = (
                    start_offset
                    + end_of_central_directory.offset_of_cd
                    + end_of_central_directory.central_directory_size
                )

                if offset == end_of_central_directory_offset:
                    break
        else:
            raise InvalidInputFormat("Missing EOCD record header in ZIP chunk.")

        has_encrypted_files = self.has_encrypted_files(
            file, start_offset, end_of_central_directory
        )

        file.seek(offset, io.SEEK_SET)
        self.cparser_le.end_of_central_directory_t(file)

        return ValidChunk(
            start_offset=start_offset,
            end_offset=file.tell(),
            is_encrypted=has_encrypted_files,
        )
