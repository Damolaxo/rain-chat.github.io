# simple profanity checker - replace with a more complete list or service
PROFANITY = {"badword1","badword2"}  # extend from file or 3rd-party API

def contains_profanity(text):
    t = text.lower()
    for w in PROFANITY:
        if w in t:
            return True
    return False
