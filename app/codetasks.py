"""Executable programming tasks, for grading that cannot be argued with.

The short-answer eval in datasets.py is graded by string and numeric matching,
which is fine but invites the objection that we chose the questions and the
marking scheme. These tasks are graded by running the generated function
against test cases: it either passes or it does not.

Two further reasons this set earns its place:

  * Each task carries an externally recognised difficulty class (easy, medium,
    hard) assigned by convention rather than by us. That gives an independent
    label to check the router's own difficulty score against -- if the score is
    arbitrary, it will not line up with these.
  * Code generation is a realistic, expensive workload. Savings measured on
    one-word trivia answers are not persuasive about production traffic.

Problem statements are written here from scratch. They describe classic
algorithmic exercises in our own words rather than reproducing any particular
site's wording.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CodeTask:
    id: str
    title: str
    level: str  # easy | medium | hard
    func: str
    prompt: str
    tests: list[tuple] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "level": self.level,
            "func": self.func,
            "tests": len(self.tests),
        }


def _p(signature: str, body: str) -> str:
    """Uniform instruction wrapper so tier comparisons are like for like."""
    return (
        f"Write a Python function `{signature}` that {body}\n\n"
        "Return only the function definition. No explanation, no example usage, "
        "no markdown fences, no imports unless strictly required."
    )


TASKS: list[CodeTask] = [
    # ---------------- easy ----------------
    CodeTask(
        "e1", "Sum of even numbers", "easy", "sum_even",
        _p("sum_even(numbers)", "returns the sum of the even integers in the list. Return 0 for an empty list."),
        [(([1, 2, 3, 4, 5, 6],), 12), (([],), 0), (([1, 3, 5],), 0), (([-2, -4, 3],), -6)],
    ),
    CodeTask(
        "e2", "Reverse word order", "easy", "reverse_words",
        _p("reverse_words(sentence)", "returns the words of the sentence in reverse order, separated by single spaces."),
        [(("the sky is blue",), "blue is sky the"), (("hello",), "hello"), (("a b c d",), "d c b a")],
    ),
    CodeTask(
        "e3", "Count vowels", "easy", "count_vowels",
        _p("count_vowels(text)", "returns how many vowels (a, e, i, o, u, any case) the string contains."),
        [(("hello world",), 3), (("",), 0), (("AEIOU",), 5), (("xyz",), 0)],
    ),
    CodeTask(
        "e4", "Largest gap", "easy", "largest_gap",
        _p("largest_gap(numbers)", "returns the largest difference between any two values in the list. Return 0 if the list has fewer than two items."),
        [(([3, 9, 1, 7],), 8), (([5],), 0), (([],), 0), (([-3, 4],), 7)],
    ),
    CodeTask(
        "e5", "Palindrome check", "easy", "is_palindrome",
        _p("is_palindrome(text)", "returns True if the string reads the same forwards and backwards, ignoring case and any character that is not a letter or digit."),
        [(("A man, a plan, a canal: Panama",), True), (("hello",), False), (("",), True), (("ab@BA",), True)],
    ),

    # ---------------- medium ----------------
    CodeTask(
        "m1", "Pair summing to target", "medium", "two_sum",
        _p("two_sum(numbers, target)", "returns the indices of the two values that add up to the target, as a list of two integers in ascending order. Exactly one such pair exists."),
        [(([2, 7, 11, 15], 9), [0, 1]), (([3, 2, 4], 6), [1, 2]), (([3, 3], 6), [0, 1])],
    ),
    CodeTask(
        "m2", "Merge overlapping ranges", "medium", "merge_ranges",
        _p("merge_ranges(ranges)", "takes a list of [start, end] pairs and returns them merged so that no two overlap, sorted by start."),
        [(([[1, 3], [2, 6], [8, 10], [15, 18]],), [[1, 6], [8, 10], [15, 18]]),
         (([[1, 4], [4, 5]],), [[1, 5]]),
         (([],), [])],
    ),
    CodeTask(
        "m3", "Longest run of distinct characters", "medium", "longest_distinct",
        _p("longest_distinct(text)", "returns the length of the longest substring that contains no repeated character."),
        [(("abcabcbb",), 3), (("bbbbb",), 1), (("pwwkew",), 3), (("",), 0)],
    ),
    CodeTask(
        "m4", "Balanced brackets", "medium", "is_balanced",
        _p("is_balanced(text)", "returns True if every round, square and curly bracket in the string is closed in the correct order."),
        [(("()[]{}",), True), (("(]",), False), (("([{}])",), True), (("(",), False), (("",), True)],
    ),
    CodeTask(
        "m5", "Group anagrams", "medium", "group_anagrams",
        _p("group_anagrams(words)", "groups the words that are anagrams of each other. Return a list of groups, each group sorted alphabetically, and the groups sorted by their first element."),
        [((["eat", "tea", "tan", "ate", "nat", "bat"],), [["ate", "eat", "tea"], ["bat"], ["nat", "tan"]]),
         (([],), []),
         ((["abc"],), [["abc"]])],
    ),

    # ---------------- hard ----------------
    CodeTask(
        "h1", "Median of two sorted lists", "hard", "median_sorted",
        _p("median_sorted(a, b)", "returns the median of the two sorted lists combined, as a float."),
        [(([1, 3], [2]), 2.0), (([1, 2], [3, 4]), 2.5), (([], [1]), 1.0), (([0, 0], [0, 0]), 0.0)],
    ),
    CodeTask(
        "h2", "Longest increasing subsequence", "hard", "lis_length",
        _p("lis_length(numbers)", "returns the length of the longest strictly increasing subsequence. The subsequence need not be contiguous."),
        [(([10, 9, 2, 5, 3, 7, 101, 18],), 4), (([0, 1, 0, 3, 2, 3],), 4), (([7, 7, 7],), 1), (([],), 0)],
    ),
    CodeTask(
        "h3", "Word segmentation", "hard", "can_segment",
        _p("can_segment(text, vocabulary)", "returns True if the string can be split into a sequence of words that all appear in the vocabulary list. Words may be reused."),
        [(("leetcode", ["leet", "code"]), True),
         (("applepenapple", ["apple", "pen"]), True),
         (("catsandog", ["cats", "dog", "sand", "and", "cat"]), False),
         (("", ["a"]), True)],
    ),
    CodeTask(
        "h4", "Smallest covering window", "hard", "min_window",
        _p("min_window(text, needed)", "returns the shortest substring of text that contains every character of needed, including duplicates. Return an empty string if there is none."),
        [(("ADOBECODEBANC", "ABC"), "BANC"), (("a", "a"), "a"), (("a", "aa"), ""), (("", "a"), "")],
    ),
]


def load(limit: int | None = None, levels: tuple[str, ...] | None = None) -> list[CodeTask]:
    items = [t for t in TASKS if not levels or t.level in levels]
    return items[:limit] if limit else items


def summary() -> dict:
    by_level: dict[str, int] = {}
    for t in TASKS:
        by_level[t.level] = by_level.get(t.level, 0) + 1
    return {
        "total": len(TASKS),
        "by_level": by_level,
        "total_assertions": sum(len(t.tests) for t in TASKS),
    }
