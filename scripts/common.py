"""Text rules shared by the fetcher: company names, US locations, roles,
seniority, industries and visa sponsorship."""

import html
import re

# ---------------------------------------------------------------- companies

_SUFFIXES = {
    "INC", "INCORPORATED", "LLC", "L L C", "CORP", "CORPORATION", "CO", "COMPANY",
    "LTD", "LIMITED", "LP", "LLP", "PLC", "PC", "PLLC", "NA", "USA", "US", "THE",
}


def normalize_company(name):
    """'Meta Platforms, Inc.' -> 'META PLATFORMS'; used to join datasets."""
    name = name.upper().split(" DBA ")[0]
    name = re.sub(r"\bL\.?\s?L\.?\s?C\b|\bL\.?\s?L\.?\s?P\b|\bL\.?\s?P\b", " LLC ", name)
    name = name.replace("&", " AND ").replace("’", "'")
    name = re.sub(r"[^A-Z0-9 ]+", " ", name.replace("'", ""))
    words = name.split()
    while words and words[-1] in _SUFFIXES:
        words.pop()
    while words and words[0] == "THE":
        words.pop(0)
    return " ".join(words)


# ---------------------------------------------------------------- locations

_STATE_CODES = (
    "AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT "
    "NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC PR"
).split()
_STATE_NAMES = (
    "Alabama|Alaska|Arizona|Arkansas|California|Colorado|Connecticut|Delaware|Florida|"
    "Georgia|Hawaii|Idaho|Illinois|Indiana|Iowa|Kansas|Kentucky|Louisiana|Maine|Maryland|"
    "Massachusetts|Michigan|Minnesota|Mississippi|Missouri|Montana|Nebraska|Nevada|"
    "New Hampshire|New Jersey|New Mexico|New York|North Carolina|North Dakota|Ohio|"
    "Oklahoma|Oregon|Pennsylvania|Rhode Island|South Carolina|South Dakota|Tennessee|"
    "Texas|Utah|Vermont|Virginia|Washington|West Virginia|Wisconsin|Wyoming"
)
_US_CITIES = (
    "San Francisco|New York|NYC|Seattle|Austin|Boston|Chicago|Los Angeles|Mountain View|"
    "Palo Alto|Menlo Park|Sunnyvale|San Jose|Santa Clara|Redmond|Bellevue|Kirkland|Denver|"
    "Boulder|Atlanta|Pittsburgh|Philadelphia|San Diego|Miami|Dallas|Houston|Phoenix|"
    "Salt Lake City|Raleigh|Durham|Portland|Minneapolis|Detroit|Nashville|Washington,? D\.?C|"
    "Arlington|Reston|Irvine|Oakland|Berkeley|Cambridge|Brooklyn|Jersey City|Columbus|"
    "Charlotte|Baltimore|Madison|Ann Arbor|Silicon Valley|Bay Area"
)
_FOREIGN = re.compile(
    r"\b(Canada|Toronto|Vancouver|Montreal|Ottawa|Waterloo|UK|United Kingdom|England|London|"
    r"India|Bangalore|Bengaluru|Hyderabad|Pune|Mumbai|Chennai|Delhi|Gurgaon|Noida|Ireland|"
    r"Dublin|Germany|Berlin|Munich|France|Paris|Netherlands|Amsterdam|Poland|Warsaw|Spain|"
    r"Singapore|Japan|Tokyo|China|Shanghai|Beijing|Taiwan|Taipei|Korea|Seoul|Australia|"
    r"Sydney|Mexico|Brazil|Israel|Tel Aviv|Switzerland|Zurich|Sweden|Romania|Philippines|"
    r"Ontario|British Columbia|Quebec|Alberta)\b",
    re.I,
)
# State codes and "US" are matched case-sensitively so "join us" is not the US.
_US_CODES = re.compile(rf",\s*({'|'.join(_STATE_CODES)})\b|\b(US|USA|U\.S\.A?\.?)(?![a-z])")
_US_NAMES = re.compile(
    rf"\b({_STATE_NAMES}|{_US_CITIES}|United States|Americas?)\b|^\s*remote\s*$|\bremote\b.*\b(US|USA)\b",
    re.I,
)


def us_locations(locations):
    """Keep only the US entries of a list of location strings."""
    kept = []
    for loc in locations:
        loc = " ".join(str(loc).split())
        if not loc or not (_US_CODES.search(loc) or _US_NAMES.search(loc)):
            continue
        if _FOREIGN.search(loc) and not re.search(r"\b(US|USA|United States)\b", loc):
            continue
        kept.append(loc)
    return kept


def split_locations(text):
    parts = re.split(r"\s*(?:;|\||/| or )\s*", text or "")
    return [p for p in parts if p.strip()]


# ---------------------------------------------------------------- roles

_INTERN = re.compile(r"\b(intern|internship|co-?op|summer 202\d|student)\b", re.I)
_SENIOR = re.compile(
    r"\b(senior|sr|staff|principal|lead|manager|director|head of|vp|vice president|"
    r"architect|distinguished|fellow|chief|expert)\b|\b(II|III|IV|[2-9])\s*(?:$|[-,(/])",
    re.I,
)
_PRODUCT_ENTRY = re.compile(r"\b(associate|rotational|new grad|apm)\b.*\bproduct manag", re.I)
_NON_CS = re.compile(
    r"\b(technician|mechanical|civil|chemical|electrical|manufacturing|process engineer|"
    r"sales|recruit\w*|nurse|accountant|accounting|marketing|legal|attorney|counsel|"
    r"clinical|pharmac\w*|designer|mechanic|construction|structural|hvac|field service|"
    r"customer success|customer support|account executive|paralegal|teacher|tutor|operator|"
    r"rf|antenna|coordinator|planner)\b",
    re.I,
)
# First match wins, so the specific job types sit above the broad families:
# "Forward Deployed AI Engineer" is an FDE role, "Software Engineer, ML" a SWE one.
SWE = "Software Engineer"
ROLES = [
    ("Forward Deployed Engineer", r"forward[- ]deployed|\bfde\b"),
    ("Data Engineer", r"data (platform |infrastructure |pipeline )?engineer|analytics engineer|\betl\b"),
    ("Embedded & Hardware", r"embedded|firmware|fpga|asic|verification engineer|silicon|\brtl\b|"
                            r"computer architecture|\bgpu\b|hardware engineer|robotics software"),
    ("Networking", r"\bnetwork(s|ing)?\b|\bnoc\b|\bccna\b|routing|switching|\bsd-?wan\b"),
    (SWE, r"software (engineer|developer|development engineer|engineering)|\bswe\b|\bsde\b"),
    ("Quant & Trading", r"\bquant\w*|\btrad(er|ing)\b"),
    ("AI & ML", r"machine learning|\bml\b|\bai\b|artificial intelligence|deep learning|"
                r"computer vision|\bnlp\b|\bllm|research (scientist|engineer)|applied scientist"),
    ("Data Science & Analytics", r"\bdata\b|analytics|business intelligence|\bbi\b|statistic"),
    ("Security", r"secur|cyber|penetration|threat|vulnerab"),
    ("Infrastructure & Cloud", r"devops|site reliability|\bsre\b|cloud|infrastructure|"
                               r"platform engineer|production engineer|systems administrator"),
    ("Product", r"product manag"),
    (SWE, r"software|developer|programmer|full[- ]?stack|front[- ]?end|"
          r"back[- ]?end|\bweb\b|mobile|android|\bios\b|sdet|\bqa\b|test automation|"
          r"algorithm|computer|solutions engineer|systems engineer|"
          r"application engineer|new grad|engineering (program|rotation)"),
]
ROLES = [(name, re.compile(rx, re.I)) for name, rx in ROLES]
# Order the site shows job types in: the most-wanted first (the site pins these too).
PINNED_ROLES = [SWE, "Data Engineer", "Forward Deployed Engineer", "Networking"]
ROLE_ORDER = list(dict.fromkeys(PINNED_ROLES + [name for name, _ in ROLES]))

_NEW_GRAD_TITLE = re.compile(
    r"new grad|new graduate|university grad|recent grad|college grad|entry[- ]level|"
    r"early[- ]career|early in career|junior|\bjr\b|associate|apprentice|residency|rotational|"
    r"campus|graduate|\b202[67]\b|\b(engineer|developer|scientist|analyst)\s+(I|1)\b(?![I\d])",
    re.I,
)
_NEW_GRAD_TEXT = re.compile(
    r"new grad|recent grad|recent college|graduat\w+ (in|by|between)\b.{0,30}202[67]|"
    r"class of 202[67]|entry[- ]level|early[- ]career|0\s*(\+|-|–|to)\s*[1-3]?\s*years|"
    r"no (prior )?(professional )?experience (is )?required",
    re.I,
)
_YEARS = re.compile(r"(\d{1,2})\s*\+?\s*(?:(?:-|–|to)\s*\d{1,2}\s*)?\+?\s*years?", re.I)


def classify_role(title):
    """Return the role family for a CS new-grad title, or None to drop it."""
    if _INTERN.search(title):
        return None
    if _PRODUCT_ENTRY.search(title):
        return "Product"
    if _SENIOR.search(title) or _NON_CS.search(title):
        return None
    for name, rx in ROLES:
        if rx.search(title):
            return name if name != "Product" else None
    return None


def min_years_required(text):
    """Smallest 'N years' figure that sits next to the word experience."""
    found = []
    for m in _YEARS.finditer(text or ""):
        window = text[m.start(): m.end() + 60].lower()
        if "experience" in window:
            found.append(int(m.group(1)))
    return min(found) if found else None


def looks_new_grad(title, text):
    """For company job boards, which mix every level, decide if a role is new-grad."""
    years = min_years_required(text)
    if years is not None and years >= 3:
        return False
    if _NEW_GRAD_TITLE.search(title) or (years is not None and years <= 1):
        return True
    return bool(_NEW_GRAD_TEXT.search(text or ""))


# ---------------------------------------------------------------- text

def html_to_text(raw):
    raw = html.unescape(raw or "")
    raw = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", raw)
    raw = re.sub(r"(?s)<[^>]+>", " ", raw)
    return " ".join(html.unescape(raw).split())


# ---------------------------------------------------------------- sponsorship

_NO_SPONSOR = re.compile(
    r"(not|unable to|cannot|can't|can not|won't|will not|does not|do not|doesn't|don't|"
    r"is not able to|are not able to|not able to|no longer)\s+(?:\w+\s+){0,4}?"
    r"(sponsor|provide sponsorship|offer sponsorship|support (?:a )?visa)\w*"
    r"|without (?:the )?(?:need (?:for|of) )?(?:current or future |future |any )?"
    r"(?:employer |visa |immigration )?sponsorship"
    r"|sponsorship (?:is |will )?(?:not|n't) (?:be )?(?:available|offered|provided|considered)"
    r"|no (?:visa |immigration |h-?1b )?sponsorship"
    r"|(?:must|required to) be (?:a )?u\.?s\.? citizens?"
    r"|u\.?s\.? citizenship (?:is )?required|requires? u\.?s\.? citizenship"
    r"|(?:only )?u\.?s\.? citizens? only|us persons? only|\bitar\b"
    r"|(?:active|current|ability to obtain|able to obtain|eligib\w+ (?:for|to obtain)|obtain and maintain|"
    r"possess|interim|secret|ts/sci|top secret)\s+(?:\w+\s+){0,4}?(?:security )?clearance",
    re.I,
)
_YES_SPONSOR = re.compile(
    r"(?:will|can|may|able to|happy to|open to|do|does)\s+(?:\w+\s+){0,3}?sponsor(?:ing|ship)?\b"
    r"|(?:visa|h-?1b|immigration) sponsorship (?:is |will be )?(?:available|offered|provided|supported)"
    r"|sponsorship (?:is )?(?:available|offered|provided)"
    r"|(?:offers?|provides?|including) (?:visa |h-?1b |immigration )?sponsorship"
    r"|sponsor (?:work )?visas",
    re.I,
)
# Sentences that only ask the applicant a question about sponsorship say nothing.
_QUESTION = re.compile(r"\b(will you|do you|are you|would you)\b[^.?]*\?", re.I)


_SENTENCE_END = re.compile(r"(?<![A-Z])[.!?]\s+(?=[A-Z*•\-])")


def _snippet(text, m):
    """The sentence around a match, clipped so the match itself always shows."""
    ends = [e.end() for e in _SENTENCE_END.finditer(text, max(0, m.start() - 400), m.end() + 400)]
    start = max([e for e in ends if e <= m.start()] + [0])
    end = min([e for e in ends if e > m.end()] + [len(text)])
    clipped_start = start < m.start() - 140
    clipped_end = end > m.end() + 140
    start = max(start, m.start() - 140)
    end = min(end, m.end() + 140)
    s = " ".join(text[start:end].split()).strip(" ,;:*​•-")
    return ("…" if clipped_start else "") + s + ("…" if clipped_end else "")


def sponsorship_from_text(text):
    """Return ('no'|'yes', evidence sentence) when the posting says so, else (None, None)."""
    if not text:
        return None, None
    clean = _QUESTION.sub(" ", text)
    neg = _NO_SPONSOR.search(clean)
    if neg:
        return "no", _snippet(clean, neg)
    pos = _YES_SPONSOR.search(clean)
    if pos:
        return "yes", _snippet(clean, pos)
    return None, None


# ---------------------------------------------------------------- industries

INDUSTRIES = [
    "AI & Machine Learning", "Big Tech", "Finance & Fintech", "Healthcare & Biotech",
    "Software & SaaS", "Consumer Tech & Marketplaces", "Hardware & Semiconductors",
    "Defense & Aerospace", "Automotive & Robotics", "Retail & E-commerce",
    "Gaming, Media & Entertainment", "Telecom & Networking", "Consulting & IT Services",
    "Government, Research & Education", "Energy & Industrial",
]
NAICS_INDUSTRY = {
    "52": "Finance & Fintech", "62": "Healthcare & Biotech",
    "61": "Government, Research & Education", "92": "Government, Research & Education",
    "44": "Retail & E-commerce", "45": "Retail & E-commerce", "71": "Gaming, Media & Entertainment",
    "21": "Energy & Industrial", "22": "Energy & Industrial", "23": "Energy & Industrial",
    "48": "Energy & Industrial", "49": "Energy & Industrial",
}
_INDUSTRY_WORDS = {
    "AI & Machine Learning": r"\b(artificial intelligence|machine learning|generative ai|llms?|foundation models?|ai research|ai lab)\b",
    "Finance & Fintech": r"\b(bank\w*|payments?|fintech|trading|hedge fund|asset management|insurance|lending|credit|brokerage|investment|financial services)\b",
    "Healthcare & Biotech": r"\b(healthcare|health care|patients?|clinical|biotech\w*|pharma\w*|medical device|hospital|genomic\w*|life sciences|therapeutics)\b",
    "Defense & Aerospace": r"\b(defense|aerospace|national security|department of defense|dod|missile|satellite|space systems|warfighter|military)\b",
    "Hardware & Semiconductors": r"\b(semiconductor\w*|chips?|silicon|wafer|integrated circuits?)\b",
    "Automotive & Robotics": r"\b(autonomous (vehicles?|driving)|automotive|robot\w*|electric vehicles?|self-driving|drones?)\b",
    "Retail & E-commerce": r"\b(retail\w*|e-?commerce|shoppers?|grocery|stores?)\b",
    "Gaming, Media & Entertainment": r"\b(games?|gaming|entertainment|streaming|media|music|studios?)\b",
    "Telecom & Networking": r"\b(telecom\w*|wireless|5g|broadband|networking equipment)\b",
    "Consulting & IT Services": r"\b(consulting|consultancy|it services|systems integrator|staffing)\b",
    "Government, Research & Education": r"\b(university|universities|national laboratory|research institute|government agency|federal agency)\b",
    "Energy & Industrial": r"\b(energy|utility|utilities|oil and gas|solar|power grid|manufacturing|logistics|construction)\b",
}
_INDUSTRY_WORDS = {k: re.compile(v, re.I) for k, v in _INDUSTRY_WORDS.items()}
_BENEFITS = re.compile(
    r"(health|medical|dental|vision|life) (insurance|benefits|coverage)|medical, dental|"
    r"401\(?k\)?|retirement|paid time off|equal opportunity[^.]*\.",
    re.I,
)


_NAME_HINTS = [
    ("Healthcare & Biotech", r"health|medical|medic|bio|pharma|therapeutic|clinic|hospital|genomic|care\b"),
    ("Finance & Fintech", r"bank|financial|capital|securities|insurance|invest|credit|pay\b|payments|trading"),
    ("Defense & Aerospace", r"aerospace|defense|defence|space|aviation|missile"),
    ("Government, Research & Education", r"universit|college|institute|laborator|\bwash u\b|school"),
    ("Hardware & Semiconductors", r"semiconductor|silicon|microelectronic|devices"),
    ("Automotive & Robotics", r"robot|motors|automotive|autonomous"),
    ("Consulting & IT Services", r"consult|staffing|it services|infotech|\binfo\b"),
    ("Energy & Industrial", r"energy|power|electric|solar|oil|gas\b|industrial|logistics"),
]
_NAME_HINTS = [(name, re.compile(rx, re.I)) for name, rx in _NAME_HINTS]


def industry_from_name(company):
    for name, rx in _NAME_HINTS:
        if rx.search(company):
            return name
    return None


def industry_from_text(text):
    """Best guess from the 'about us' part of a description; None if unclear."""
    if not text:
        return None
    head = _BENEFITS.sub(" ", text[:2500])
    scores = {name: len(rx.findall(head)) for name, rx in _INDUSTRY_WORDS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] >= 2 else None
