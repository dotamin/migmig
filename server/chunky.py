import urllib2

import constants as setting


class Chunky:
    def __init__(self, HASH, url, first_client_id, user_preferences=None):
        """
            I can improve the way chunky class handles saving chunks for clients.
            There is three ways that came to my mind :
                1. each client has its own Stack. if another client comes (second user wants to download the URL)
                    he will call build_stack() to build his new stack. the build_stack() method gives half of
                    chunks to second client. and if third client comes, he also will call build_stack().
                    If a client downloads all of his chunks in his stack, he calls build_stack to get new chunks.
                    this procedure goes until build_stack() returns zero chunk meaning all chunks have been downloaded.

                2. each client has one Stack, but there is a main stack belongs to "chunky" class.
                    each client request for new chunk, the chunky "pop" a chunk from main stack and gives
                    it to client. if client download the chunk successfully, the popped chunk goes to client stack.
                    this goes until main stack become empty.

                3. the easiest way. There is only one Stack. for every request, chunky pop a chunk and gives it
                    to client to download that chunk. The problem is in this way server cannot track chunks, and
                    clients don't know which chunk downloaded by who !
        """
        self.__clients = []

        self.__chunk_stack = Stack()

        self.__current_chunks = []

        self._HASH = HASH
        self._URL = url
        self._file_name = None
        self.__clients.append(first_client_id)
        self.user_preferences = user_preferences

        self.content_len = 0
        self.total_chunks = 0
        self.content_type = None
        self.accept_ranges = None

        self.status = setting.UNKNOWN

        # BLOCKING
        if self.get_headers():
            # if result of get_headers() is ready:
            self.chunk_size = self.compute_chunk_size()
            # If we have chunk_size:
            self.build_stack()
            self.total_chunks = self.__chunk_stack.size()

    def add_client(self, cl):
        self.__clients.append(cl)

    def register(self, client_id):
        if client_id not in self.__clients:
            self.add_client(client_id)

    def new(self, client_id):
        """
            Return a dictionary containing URL status and len and other informations.
                return : {status, identifier, URL, file_name, client_id, content_len}
        """
        if self.status == setting.UNKNOWN:
            if (not self.accept_ranges) or (self.accept_ranges != 'bytes'):
                self.status = setting.RANGE_NOT_SUPPORTED
            elif not self.content_len:
                self.status = setting.UNKNOWN_HEADER
            else:
                self.status = setting.OK

        result = {
            'status': self.status,
            'identifier': self._HASH,
            'url': self._URL,
            'client_id': client_id,
            'file_name': self._file_name,
            'content_len': self.content_len,
            'total_chunks': self.total_chunks
        }

        return result

    def fetch(self, client_id, latest_downloaded_chunk):
        """
        Gets latest chunk which downloaded by client, and removes it from the current_download list.
        Gives client a new chunk.
        :return: dict
        TO-DO: in new versions, you can save downloaded chunks into another stack.
        """
        self.__chunk_stack.remove_current(latest_downloaded_chunk)

        if self.__chunk_stack.is_empty():
            result = {'status': setting.DONE}
        else:
            # NOTE: if a chunk popped from stack, it automatically considers as a "current downloading chunk"
            num, start, end = self.__chunk_stack.pop()
            chunk_name = self._file_name + '.' + '%.4d' % num
            result = {
                'status': setting.OK,
                'chunk_num': num,
                'chunk_size': self.chunk_size,
                'start_byte': start,
                'end_byte': end,
                'chunk_name': chunk_name
            }
        # print '[+] ' + str(result)

        return result

    def is_cleaned(self):
        """
        Returns True if all chunks have been downloaded.
        :return: boolean
        """
        if self.__chunk_stack.is_empty() and self.__chunk_stack.is_current_empty():
            return True
        return False

    def get_headers(self):
        """
            Apparently twisted don't have any SIMPLE method equivalent to urlopen !
            I wrote this method 'BLOCKING'. i shouldn't do this, but who cares ? :D
        """
        try:
            url_obj = urllib2.urlopen(self._URL)

            self.content_type = url_obj.info().getheader('content-type')
            self.content_len = url_obj.info().getheader('content-length')
            self.content_len = int(self.content_len)

            self.accept_ranges = url_obj.info().getheader('accept-ranges')
            self._file_name = self.extract_file_name(url_obj.info().getheader('content-disposition'))

            return url_obj

        except urllib2.HTTPError, e:
            if e.code == 404:
                # BAD URL, file not found
                self.status = setting.NOT_FOUND
            return None

    def compute_chunk_size(self):
        # if len is 0, how i can compute chunk len ?
        size = 0
        if not self.content_len:
            return size
        # Maybe its better to use a good algorithm for
        #  computing chunk-size base on file-size and number of users
        initial_size = [
            (5242880, 51200),  # <5 MB : 50 KB
            (20971520, 1048576),  # <20 MB (file size) : 1 MB (chunk size)
            (52428800, 3145728),  # <50 MB : 3 MB
            (209715200, 5242880),  # <200 MB : 5 MB
            (1073741824, 10485760),  # <1 GB : 10 MB
            (10737418240, 20971520),  # <10 GB : 20 MB
        ]
        for f_size, ch_size in initial_size:
            if self.content_len < f_size:
                size = ch_size
                break

        if not size:
            size = 41943040  # 40 MB, maximum chunk size

        try:
            demanded_size = int(self.user_preferences.get('chunk-size'))
            # print 'demand: ', demanded_size, type(demanded_size)
            if demanded_size and demanded_size < self.content_len // 4:
                size = demanded_size
        except:
            pass

        return size

    def build_stack(self):
        # 1. make a tupe for each chunk: (chunk_num, start_byte, end_byte)
        # 2. save it into stack
        size = self.chunk_size
        tmp, num, start = 0, 0, 0
        flag = False

        while not flag:
            end = start + size - 1

            if end >= self.content_len:
                # make sure last chunk is correct
                end = self.content_len
                flag = True

            chunk = (num, start, end)
            self.__chunk_stack.push(chunk)

            start = end + 1
            num += 1

        # because stack is LIFO, we dont want to pop LAST CHUNK first !
        self.__chunk_stack.reverse()

    def extract_file_name(self, disposition=None):
        """
        Extract file name. it can be done by extracting 'content-disposition' in
        HTTP header, or using URL.
        """
        # TO-D0: what about urls that redirect the requester ?
        if disposition:
            return disposition

        base_name = self._URL.split('/')[-1]
        if '?' in base_name:
            base_name = base_name.split('?')[0]
        return base_name


class Stack:
    def __init__(self):
        # Last in First out
        self.__storage = []
        self.__currents = []

    def pop(self):
        # pop the
        the_chunk = self.__storage.pop()
        self.add_current(the_chunk)
        return the_chunk

    def push(self, value):
        self.__storage.append(value)

    def get(self):
        return self.__storage[-1]

    def add_current(self, ch):
        self.__currents.append(ch)

    def remove_current(self, chunk_num):
        if chunk_num:
            chunk_num = int(chunk_num)
            for ch in self.__currents:
                if chunk_num == ch[0]:
                    self.__currents.remove(ch)
                    return True
        return False


    def is_empty(self):
        if not len(self.__storage):
            return True
        return False

    def is_current_empty(self):
        if not len(self.__currents):
            return True
        return False

    def size(self):
        return len(self.__storage)

    def reverse(self):
        self.__storage.reverse()
