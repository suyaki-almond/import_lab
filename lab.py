import datetime

# phoneme = 音素
# vowel = 母音
# consonants = 子音


class phoneme:
    # phoneme_literals = ['a', 'i', 'u', 'e', 'o', 'N', 'k', 'g', 's', 'sh', 'z', 'j', 't', 'ch', 'ts', 'd', 'n',
    #          'h', 'f', 'b', 'p', 'm', 'y', 'r', 'w', 'ky', 'gy', 'sy', 'ny', 'by', 'py', 'my', 'ry', 'v', 'cl', 'pau']
    vowel_literals = ['a', 'i', 'u', 'e', 'o', 'N']
    consonants_literals = ['k', 'g', 's', 'sh', 'z', 'j', 't', 'ch', 'ts', 'd', 'n', 'h', 'f',
                           'b', 'p', 'm', 'y', 'r', 'w', 'ky', 'gy', 'sy', 'ny', 'hy', 'by', 'py', 'my', 'ry', 'v']
    phoneme_literals = vowel_literals + consonants_literals  # + ['cl', 'pau']

    def __init__(self, phoneme: str, timingB: int, timingE: int) -> None:
        self.phoneme = phoneme
        self.timingB = timingB
        self.timingE = timingE

    def __str__(self) -> str:
        return f"{self._timingB.microseconds} {self._timingE.microseconds} {self.phoneme}"

    @property
    def phoneme(self) -> str:
        return self._phoneme

    @property
    def timingB(self) -> float:
        return self._timingB.seconds + self._timingB.microseconds * 0.000001

    @property
    def timingE(self) -> float:
        return self._timingE.seconds + self._timingE.microseconds * 0.000001

    @phoneme.setter
    def phoneme(self, phoneme: str):
        # if not phoneme in self.phoneme_literals:
        #     raise ValueError(f"存在しない音素 : \"{phoneme}\"")
        self._phoneme = phoneme

    @timingB.setter
    def timingB(self, timing: int):
        self._timingB = datetime.timedelta(microseconds=timing*0.1)

    @timingE.setter
    def timingE(self, timing: int):
        self._timingE = datetime.timedelta(microseconds=timing*0.1)


class lab_words:
    def __init__(self, filepath: str = ''):
        self.phoneme_list: list[phoneme] = []

        if filepath != '':
            with open(filepath, encoding='utf-8') as f:  # BOM Check
                enc = 'utf-8-sig' if f.read()[0] == '\ufeff' else 'utf-8'

            with open(file=filepath, mode='r', encoding=enc) as f:
                for line in f:
                    s = line.split()
                    self.phoneme_list.append(
                        phoneme(s[2], int(s[0]), int(s[1])))

    def __str__(self) -> str:
        s = ""
        for p in self.phoneme_list:
            s.join(f"{p.str()}\n")
        return s

    def split(self, sensitive: bool = False) -> list['lab_words']:
        sentence: list[lab_words] = []
        pau = 0
        s, e = 0, 0
        sen = 0 if sensitive else 1
        for p in self.phoneme_list:
            if p.phoneme == "pau":
                pau += 1
            else:
                if pau > sen:
                    end = e-pau
                    if s < end:
                        w = lab_words()
                        w.phoneme_list = self.phoneme_list[s:end]
                        sentence.append(w)
                        s = e-1
                pau = 0
            e += 1
        if len(sentence) != 0:
            w = lab_words()
            w.phoneme_list = self.phoneme_list[s:e-pau]
            sentence.append(w)
        return sentence
