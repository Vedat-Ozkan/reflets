"""The short legend each variant carries, the kind of text a tool description would hold."""
import codecs_n1 as c

BASE = (
    "Header: div = units per quarter note, ts = time signature, ks = key signature (3f = three flats, 2s = two sharps, 0 = none). "
    "Each `mN len=…` line starts bar N (len in div units; m0 is a pickup). Each `staff.voice:` line is one voice of that bar; "
    "staves are numbered from the top. A bare number sets the duration in div units for the notes after it; `+` joins the notes "
    "of a chord; `r` is a rest of the current duration; a leading `g` marks a grace note (no duration); a trailing `~` ties the "
    "note to the next. Pitches are sounding pitches with spelling and octave (C4 = middle C)."
)
R = (
    " `mN = mK` means bar N is identical to bar K in every voice and in length. A voice line `s.v = mK` means that voice is "
    "identical to voice s.v of bar K."
)
T = (
    " `s.v = mK +M2` means voice s.v of bar K moved by that interval with the same rhythm (+ up, - down; P perfect, M major, "
    "m minor, A augmented, d diminished; -P4 = down a perfect fourth), each pitch spelled by the interval."
)
P = (
    " Inside a voice line, `(X)*n` means X written n times in a row and `X*n` the single token X n times; "
    "durations carry on as if it were written out."
)
O_EXAMPLE = "12 C4 E G C B4 G+B+D5 F"
O = (
    " Octaves are relative. In each voice line the first pitch has its octave digit. A later pitch without a digit is in the "
    "octave that puts it within a fourth (at most three letter steps, accidentals ignored) of its reference: for a note or the "
    "first note of a chord, the previous note, or the first note of the previous chord; for a later note of a chord, that chord's first note. "
    "A pitch with a digit is absolute. Example: `" + O_EXAMPLE + "` = `" + c.octaves_decode(O_EXAMPLE) + "`."
)
ORDER = " Expand references first (copy the referenced line), then repeats, then octaves."
OVERVIEW = (
    "Header: div = units per quarter note, ts = time signature, ks = key signature (3f = three flats, 2s = two sharps, 0 = none). "
    "This is an overview, not the full score. Per bar (`mN len=…`, len in div units, m0 a pickup): `top:` is the highest note "
    "attacked at each moment across all staves, written as a voice: a bare number sets the duration in div units for the notes "
    "after it, `r` is a rest, a trailing `~` a tie. Inner voices and the rhythm of the other parts are left out. "
    "Pitches are sounding pitches with spelling and octave (C4 = middle C)."
)
V1 = " `bass:` gives, per beat, the lowest note sounding at the start of that beat (`r` = nothing sounds)."
V2 = (
    " `beats:` gives, per beat and separated by `|`, the lowest note sounding at the start of the beat with its octave, then "
    "the other pitch classes sounding during that beat, low to high."
)


def legend(variant: str) -> str:
    if variant.startswith("V"):
        return OVERVIEW + (V1 if variant == "V1" else V2)
    text = BASE
    if "R" in variant:
        text += R
    if "T" in variant:
        text += T
    if "P" in variant:
        text += P
    if "O" in variant:
        text += O
    if sum(x in variant for x in "RPO") > 1:
        text += ORDER
    return text
