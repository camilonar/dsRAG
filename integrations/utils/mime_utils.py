import mimetypes
from os import PathLike
from typing import Union, Optional

def __add_mimetypes():
    # Some OS don't have certain MIME types registered, so we make sure that the important ones are here
    mimetypes.add_type("application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".docx")
    mimetypes.add_type("application/pdf", ".pdf")
    mimetypes.add_type("text/plain", ".txt")
    mimetypes.add_type("text/markdown", ".md")


def guess_type(url: Union[str, PathLike[str]],
               strict: bool = True) -> tuple[Optional[str], Optional[str]]:
    """
    Wrapper for :func:`mimetypes.guess_type`.
    Guess the type of a file based on its URL.

    Return value is a tuple (type, encoding) where type is None if the
    type can't be guessed (no or unknown suffix) or a string of the
    form type/subtype, usable for a MIME Content-type header; and
    encoding is None for no encoding or the name of the program used
    to encode (e.g. compress or gzip).  The mappings are table
    driven.  Encoding suffixes are case sensitive; type suffixes are
    first tried case sensitive, then case insensitive.

    The suffixes .tgz, .taz and .tz (case sensitive!) are all mapped
    to ".tar.gz".  (This is table-driven too, using the dictionary
    suffix_map).

    Optional `strict' argument when false adds a bunch of commonly found, but
    non-standard types.
    """
    return mimetypes.guess_type(url, strict=strict)


# We add the types when the module is imported
__add_mimetypes()