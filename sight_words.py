# Dolch Sight Words organized by level
SIGHT_WORDS = {
    "pre-primer": [
        "a", "and", "away", "big", "blue", "can", "come", "down", "find",
        "for", "funny", "go", "help", "here", "I", "in", "is", "it", "jump",
        "little", "look", "make", "me", "my", "not", "one", "play", "red",
        "run", "said", "see", "the", "three", "to", "two", "up", "we",
        "where", "yellow", "you"
    ],
    "primer": [
        "all", "am", "are", "at", "ate", "be", "black", "brown", "but",
        "came", "did", "do", "eat", "four", "get", "good", "have", "he",
        "into", "like", "must", "new", "no", "now", "on", "our", "out",
        "please", "pretty", "ran", "ride", "saw", "say", "she", "so",
        "soon", "that", "there", "they", "this", "too", "under", "want",
        "was", "well", "went", "what", "white", "who", "will", "with", "yes"
    ],
    "grade1": [
        "after", "again", "an", "any", "ask", "as", "by", "could", "every",
        "fly", "from", "give", "going", "had", "has", "her", "him", "his",
        "how", "just", "know", "let", "live", "may", "of", "old", "once",
        "open", "over", "put", "round", "some", "stop", "take", "thank",
        "them", "think", "walk", "were", "when"
    ],
    "grade2": [
        "always", "around", "because", "been", "before", "best", "both",
        "buy", "call", "cold", "does", "don't", "fast", "first", "five",
        "found", "gave", "goes", "green", "its", "made", "many", "off",
        "or", "pull", "read", "right", "sing", "sit", "sleep", "tell",
        "their", "these", "those", "upon", "us", "use", "very", "wash",
        "which", "why", "wish", "work", "would", "write", "your"
    ],
    "grade3": [
        "about", "better", "bring", "carry", "clean", "cut", "done", "draw",
        "drink", "eight", "fall", "far", "full", "got", "grow", "hold",
        "hot", "hurt", "if", "keep", "kind", "laugh", "light", "long",
        "much", "myself", "never", "only", "own", "pick", "seven", "shall",
        "show", "six", "small", "start", "ten", "today", "together", "try",
        "warm"
    ]
}

# Flat ordered list for progression
ORDERED_SIGHT_WORDS = []
for level in ["pre-primer", "primer", "grade1", "grade2", "grade3"]:
    ORDERED_SIGHT_WORDS.extend(SIGHT_WORDS[level])

# Word level lookup
WORD_LEVEL = {}
for level, words in SIGHT_WORDS.items():
    for word in words:
        WORD_LEVEL[word.lower()] = level
