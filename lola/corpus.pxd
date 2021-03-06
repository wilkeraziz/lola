cimport numpy as np
from lola.ptypes cimport uint_t


cdef class Corpus:
    """
    A corpus is a collection of sentences.
    Each sentence is a sequence of words.

    Internally, words are represented as integers for compactness and quick indexing using numpy arrays.

    Remark: This object offers no guarantee as to which exact index any word will get. Not even the NULL word.
    """

    cdef readonly object _lookup
    cdef readonly uint_t[::1] _inverse
    cdef readonly uint_t[::1] _boundaries
    cdef size_t _max_len

    cpdef size_t max_len(self)

    cpdef uint_t[::1] sentence(self, size_t i)

    cpdef translate(self, size_t i)

    cpdef size_t vocab_size(self)

    cpdef size_t corpus_size(self)

    cpdef size_t n_sentences(self)

    cpdef Corpus underlying(self)


cdef class CorpusView(Corpus):

    cdef:
        size_t _offset
        size_t _size
        Corpus _corpus
