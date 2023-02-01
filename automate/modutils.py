import zlib
from pathlib import Path
from typing import Optional

from ue.stream import MemoryStream
from utils.log import get_logger

__all__ = (
    'DecompressionError',
    'unpackModFile',
    'readACFFile',
    'readModInfo',
    'readModMetaInfo',
    'readUnrealString',
    'loadFileAsStream',
)

logger = get_logger(__name__)


class DecompressionError(Exception):
    '''An error occurred during file decompression.'''


# Compressed file structure:
#   8   fixed token 0x9e2a83c1
#   8   chunk size (when uncompressed)
#   8   total compressed size
#   8   total uncompressed size
#   repeat:
#     8   chunk compressed size
#     8   chunk uncompressed size (matches chunk size in all but the last chunk)
def unpackModFile(src: str, dst: str):
    f = loadFileAsStream(src)
    token = f.readUInt64()
    sizeUnpackedChunk = f.readUInt64()
    _ = f.readUInt64()  # sizePacked
    sizeUnpacked = f.readUInt64()

    assert token == 0x9e2a83c1, DecompressionError("Invalid header in downloaded mod")

    chunkSizes = []
    sizeFound = 0
    while sizeFound < sizeUnpacked:
        chunkSizeCompressed = f.readUInt64()
        chunkSizeUnompressed = f.readUInt64()
        chunkSizes.append((chunkSizeCompressed, chunkSizeUnompressed))
        sizeFound += chunkSizeUnompressed

    assert sizeFound == sizeUnpacked, DecompressionError("Invalid chunk sizes in downloaded mod")

    with open(dst, 'wb', buffering=64 * 1024) as of:
        for i, (csCompressed, csUncompressed) in enumerate(chunkSizes):
            chunkData = f.readBytes(csCompressed)
            uncompressedChunkData = zlib.decompress(chunkData)
            del chunkData

            assert len(uncompressedChunkData) == csUncompressed, DecompressionError(
                "Decompression of downloaded mod chunk failed verification")
            assert len(uncompressedChunkData) == sizeUnpackedChunk or i + 1 == len(chunkSizes), DecompressionError(
                "Chunk of downloaded mod is not the expected size")

            of.write(uncompressedChunkData)
            del uncompressedChunkData


def readACFFile(filename: str | Path, outputType: type = dict):
    content = Path(filename).read_text(encoding='utf-8')
    data = parseAcf(content, outputType)
    return data


def parseAcf(data: str, outputType=dict):
    '''Adapted from github.com/leovp/steamfiles (MIT licensed).'''
    output = outputType()
    current_section = output
    sections: list[str] = []

    for line in data.splitlines():
        if not line:
            break
        line = line.strip()
        try:
            key, value = line.split(None, 1)
            key = key.replace('"', '').lstrip()
            value = value.replace('"', '').rstrip()
        except ValueError:
            if line == '{':
                # Initialize the last added section.
                current = output
                for i in sections[:-1]:
                    current = current[i]
                current[sections[-1]] = outputType()
                current_section = current[sections[-1]]
            elif line == '}':
                # Remove the last section from the queue.
                sections.pop()
            else:
                # Add a new section to the queue.
                sections.append(line.replace('"', ''))
            continue

        current_section[key] = value

    return output


def readModInfo(filename):
    f = loadFileAsStream(filename)
    modname = readUnrealString(f)
    countMaps = f.readUInt32()
    maps = (readUnrealString(f) for i in range(countMaps))
    result = dict(modname=modname, maps=tuple(maps))
    return result


def readModMetaInfo(filename):
    f = loadFileAsStream(filename)
    countEntries = f.readUInt32()
    entries = [(readUnrealString(f), readUnrealString(f)) for i in range(countEntries)]
    return dict(entries)


def readUnrealString(f: MemoryStream) -> Optional[str]:
    count = f.readUInt32()
    if count < 0:
        raise ValueError("UTF16 string detected - add support here!")
    if count == 0:
        return None
    data = f.readBytes(count)
    string = data.decode('utf8')[:-1]
    return string


def loadFileAsStream(filename):
    with open(filename, 'rb') as f:
        data = f.read()
        mem = memoryview(data)
        stream = MemoryStream(mem)
        return stream
