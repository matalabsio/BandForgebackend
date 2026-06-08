"""Generate MT2 reading interface JSON from founder .pages content."""

from __future__ import annotations

import json
from pathlib import Path

M02 = "a0000000-0000-4000-8000-000000000002"
OUT = Path(__file__).resolve().parents[2] / "test" / "MT2" / "RT" / "interface"

PASSAGE_1 = """How Animals Make Sense of Their World

A    During much of the twentieth century, scientists were reluctant to credit animals with anything resembling thought. Behaviour that appeared intelligent was usually explained as instinct — fixed responses shaped by evolution rather than genuine reasoning. A barking dog or a nest-building bird was seen as following an inherited programme, not making a decision. This cautious view has gradually given way to a more generous picture. The field known as animal cognition now studies how creatures perceive, remember, and respond to the world around them, drawing on careful observation in the wild as well as controlled laboratory experiments. A growing body of evidence suggests that many species process information in surprisingly flexible ways. Researchers are careful, however, to distinguish between behaviour that merely looks clever and behaviour that genuinely involves understanding, since the two can be difficult to tell apart.

B    Communication has provided some of the most striking examples of this flexibility. The Austrian zoologist Karl von Frisch spent decades decoding the so-called waggle dance of honeybees, a looping movement performed inside the hive that conveys both the direction and the distance of a food source. The angle of the dance indicates direction relative to the sun, while its duration signals how far away the food lies. His work was so influential that he shared the Nobel Prize in 1973. Many years later, the researchers Robert Seyfarth and Dorothy Cheney studied vervet monkeys in East Africa and showed that they use distinct alarm calls for different predators. One sound sends the group climbing into the trees to escape leopards, while another makes them look upward to watch for eagles. The calls function almost like words, each tied to a specific meaning rather than simply expressing fear.

C    Problem-solving offers further evidence of mental flexibility. New Caledonian crows are perhaps the best-studied example. In the wild they shape twigs and leaves into hooks to extract insects from narrow crevices, and in laboratory tests they have solved multi-step puzzles that require using one tool to obtain another. In one widely reported experiment, a captive crow named Betty bent a straight piece of wire into a hook in order to lift a small bucket of food out of a tube — a solution she had never been trained to produce. Although later studies showed that wild crows also bend materials naturally, the birds' ability to adapt their methods to new situations remains impressive. Such behaviour suggests that they can picture a goal and work out the sequence of steps needed to reach it.

D    Memory, too, can be remarkably sophisticated. Western scrub jays hide thousands of food items across their territory and later recover them with considerable accuracy. Research led by Nicola Clayton at the University of Cambridge demonstrated that these birds remember not only where they stored food but also what they stored and how long ago they did so. Perishable items such as insects are retrieved before they have time to spoil, while longer-lasting seeds may be left for several days. The jays even appear to change their hiding behaviour when other birds are watching, returning later to move the food to a new location. This ability to keep track of specific past events was once thought to be unique to humans.

E    Not every impressive performance withstands close scrutiny, and scientists remain wary of reading too much into animal behaviour. The most famous cautionary tale is that of Clever Hans, a horse in early twentieth-century Germany that appeared to solve arithmetic problems by tapping its hoof the correct number of times. Careful testing eventually revealed that Hans was not calculating at all; instead, he was responding to tiny, unconscious changes in the posture and expression of the people around him, stopping when they relaxed. The episode is still used to warn against anthropomorphism — the tendency to assume that animals think in exactly the same way as humans. Modern experiments are therefore designed with strict controls to rule out such hidden influences.

F    Despite growing evidence for animal cognition, drawing firm conclusions remains difficult. A behaviour that looks thoughtful in one setting may have a simpler explanation in another, and scientists therefore hesitate to attribute human-like understanding without rigorous proof. Nevertheless, the findings already have practical implications. Many mammals display social awareness and adjust their behaviour to circumstances in ways that challenge old assumptions about mindless instinct. How humans house, train, and study animals on farms, in laboratories, and in zoos is increasingly shaped by these questions. Researchers stress, however, that respecting animal welfare is not the same as claiming animals reason exactly as people do."""

PASSAGE_2 = """The Unfulfilled Promise of Educational Technology

A    For more than a century, each new communication technology has arrived in classrooms accompanied by bold predictions. In the 1920s, the inventor Thomas Edison declared that motion pictures would soon replace textbooks; later, radio, television, and the personal computer were each described as forces that would transform how children learn. The pattern has been remarkably consistent: an initial wave of enthusiasm, followed by disappointment as the new tool fails to deliver the promised revolution. Understanding why this cycle repeats has become an important question for researchers, particularly as digital devices now occupy a central place in schools worldwide. The mismatch between confident forecasts and actual classroom results raises a deeper issue: whether the problem lies in the technology itself, or in the assumptions made about what it can achieve.

B    The most recent example of this cycle is the massive open online course, or MOOC. When platforms such as Coursera and edX were launched in 2012, commentators described that period as the "year of the MOOC" and predicted that free, university-level courses would make traditional institutions obsolete. Enrolment figures were indeed enormous, with individual courses attracting hundreds of thousands of registrations. Yet completion told a different story. A widely cited analysis by researchers at the University of Pennsylvania found that, on average, only about four per cent of those who signed up for a course finished it. Most participants, moreover, already held a degree, suggesting that the courses were extending opportunity for the well-educated rather than reaching new learners. By the end of the decade, most universities had quietly accepted that MOOCs would complement campus teaching rather than replace it.

C    Similar gaps between expectation and outcome have appeared in schools. Many governments have invested heavily in schemes to provide every pupil with a laptop or tablet, on the assumption that access to devices would automatically raise achievement. The evidence has been mixed at best. A large 2015 report by the Organisation for Economic Co-operation and Development examined data from dozens of countries and concluded that students who used computers very frequently at school tended to perform worse in reading and mathematics, even after social background was taken into account. The report did not argue that technology was harmful in itself, but it questioned the belief that simply distributing hardware would improve results. What mattered, the authors suggested, was not whether computers were present but how, and how often, they were used.

D    Researchers who study these failures point to a recurring misunderstanding. Technology, they argue, is not a substitute for skilled teaching; it is a tool whose value depends entirely on how it is used. A tablet can display an excellent lesson or a poor one, and a pupil left alone with a device may simply become distracted. There is also evidence of a so-called second digital divide. While access to devices has become more equal, the ability to use them productively has not. Students from advantaged homes are more likely to use technology for learning, whereas those from poorer backgrounds more often use the same devices for entertainment, which can widen rather than narrow existing gaps in attainment.

E    None of this means that technology has no place in education. When it is carefully designed and closely integrated with teaching, it can produce genuine benefits. Adaptive learning software, which adjusts the difficulty of questions to each learner's performance, has shown modest but consistent gains in subjects such as mathematics. The underlying idea is old: in 1984 the psychologist Benjamin Bloom observed that a student receiving one-to-one tutoring could outperform around ninety-eight per cent of pupils taught in conventional classes, a result he called the "two sigma problem". Personalised software cannot fully reproduce a human tutor, but it can offer some of the individual attention that large classes make impossible. Crucially, the most successful programmes are not those that replace teachers but those that support them — adjusting content while keeping a human adult in charge of motivation and discipline. As long as schools focus narrowly on hardware adoption rather than on training teachers to use tools well, the cycle of promise and disappointment is likely to continue."""

PASSAGE_3 = """The Psychology of Leadership in Times of Crisis

A    When a nation faces sudden danger — a war, an economic collapse, a pandemic — public attention turns sharply towards those in charge. Citizens expect their leaders to act with clarity and resolve, and historians often judge a presidency or premiership by its conduct during such moments. Yet the psychological reality of leading under crisis is considerably more complicated than the popular image of the calm, all-seeing decision-maker suggests. Crises do not merely test character; they distort the conditions under which judgement is exercised, compressing the time available for reflection and raising the stakes of every choice. Understanding how leaders actually behave under such pressure has therefore become a significant concern for political psychologists. Their work draws on historical case studies, interviews, and controlled experiments, and it consistently challenges the assumption that good leadership in a crisis is simply a matter of strength of will.

B    One of the most consistent findings is that acute stress narrows the range of options a leader is able to consider. Under pressure, decision-making tends to become faster but also more rigid, with individuals relying on familiar assumptions rather than seeking fresh information. This tendency is intensified within small groups of advisers. In 1972 the psychologist Irving Janis introduced the term "groupthink" to describe how cohesive teams, anxious to preserve unity, can suppress dissent and converge prematurely on a flawed course of action. His central example was the 1961 decision by the United States government to support an invasion of Cuba at the Bay of Pigs — a plan whose obvious weaknesses went unchallenged because no adviser wished to appear disloyal. Janis argued that the problem was not a lack of intelligence among those involved, but a social atmosphere in which doubt felt inappropriate.

C    Crisis leadership is not only a matter of private decision-making; it is also, perhaps above all, an exercise in public communication. A leader's words can either steady a frightened population or deepen its alarm. Research into political rhetoric suggests that audiences respond less to the technical content of a message than to the impression of competence and sincerity it conveys. During the economic emergency of the 1930s, the broadcasts of the American president Franklin Roosevelt were widely credited with restoring public confidence, not because they offered detailed policy but because they projected steadiness and candour. The lesson drawn by later scholars was that the management of emotion is as central to crisis leadership as the management of events.

D    A more troubling pattern concerns the projection of certainty. Because populations crave reassurance, leaders are rewarded for appearing confident, even when the situation is genuinely unclear. This creates an incentive to overstate what is known and to understate what is not. The political scientist Philip Tetlock, in a long study of expert forecasting, found that confident, decisive predictions were no more accurate than cautious ones — and were often less so — yet they consistently attracted more attention and trust. Applied to crisis leadership, this finding implies a hidden cost: the very assurance that calms the public in the short term may discourage the honest revision of policy when circumstances change.

E    It is tempting to assume that emergencies reveal a leader's "true self", or even that they create new qualities under pressure. The evidence points instead to amplification. Crises rarely transform personality; more often they exaggerate dispositions that were already present. A leader inclined towards caution becomes more hesitant, while one prone to boldness becomes more reckless. For this reason, psychologists who study political behaviour place considerable weight on a leader's record before a crisis arrives, treating it as a better guide to likely conduct than any promise made once danger is at hand. This is one reason why sudden shifts in a leader's behaviour during a crisis are often viewed by researchers with scepticism rather than admiration."""

HEADINGS_1 = [
    {"label": "i", "text": "Replacing earlier scepticism with a new field of study"},
    {"label": "ii", "text": "How animals communicate with each other"},
    {"label": "iii", "text": "Evidence of planning in tool use"},
    {"label": "iv", "text": "Remembering where food was hidden"},
    {"label": "v", "text": "A famous case of mistaken intelligence"},
    {"label": "vi", "text": "Practical implications for how animals are treated"},
    {"label": "vii", "text": "Why laboratory conditions are essential"},
]

HEADINGS_2 = [
    {"label": "i", "text": "High enrolment but low completion"},
    {"label": "ii", "text": "Hardware alone does not raise standards"},
    {"label": "iii", "text": "Technology depends on how teachers use it"},
    {"label": "iv", "text": "A second form of inequality in digital access"},
    {"label": "v", "text": "When software can approximate individual teaching"},
    {"label": "vi", "text": "Why governments prefer laptops to textbooks"},
    {"label": "vii", "text": "The role of radio in early classrooms"},
]

HEADINGS_3 = [
    {"label": "i", "text": "How stress alters private decision-making"},
    {"label": "ii", "text": "Why advisers may fail to challenge a leader"},
    {"label": "iii", "text": "The role of public speaking during emergencies"},
    {"label": "iv", "text": "The temptation to appear more certain than the facts allow"},
    {"label": "v", "text": "Why earlier behaviour may predict crisis conduct"},
    {"label": "vi", "text": "The advantages of calm leadership"},
    {"label": "vii", "text": "How historians judge failed policies"},
]


def _payload(
    *,
    resource_id: str,
    part: int,
    title: str,
    passage: str,
    groups: list,
) -> dict:
    return {
        "resource_id": resource_id,
        "skill": "reading",
        "task": part,
        "title": title,
        "description": f"Academic Reading — MT2 passage {part}.",
        "mock_test_id": M02,
        "passage_text": passage,
        "question_groups": groups,
    }


P1 = _payload(
    resource_id="ielts_reading_mt2_passage_1",
    part=1,
    title="How Animals Make Sense of Their World",
    passage=PASSAGE_1,
    groups=[
        {
            "group_id": "mt2_p1_tfng_1_5",
            "range": "1-5",
            "question_type": "tfng",
            "instruction": "Do the following statements agree with the information given in the passage?",
            "questions": [
                {"number": 1, "statement": "Scientists once believed that intelligent-looking animal behaviour was caused by instinct.", "answer": "TRUE"},
                {"number": 2, "statement": "Karl von Frisch demonstrated that the honeybee waggle dance indicates direction and distance.", "answer": "TRUE"},
                {"number": 3, "statement": "Vervet monkeys use the same alarm call for every predator.", "answer": "FALSE"},
                {"number": 4, "statement": "Betty the crow had been trained to bend wire before the experiment.", "answer": "FALSE"},
                {"number": 5, "statement": "Western scrub jays remember when as well as where they hid food.", "answer": "TRUE"},
            ],
        },
        {
            "group_id": "mt2_p1_headings_6_9",
            "range": "6-9",
            "question_type": "matching_headings",
            "instruction": "The passage has six paragraphs, A–F. Choose the correct heading for paragraphs C–F from the list of headings below.",
            "headings": HEADINGS_1,
            "questions": [
                {"number": 6, "paragraph": "C", "answer": "iii"},
                {"number": 7, "paragraph": "D", "answer": "iv"},
                {"number": 8, "paragraph": "E", "answer": "v"},
                {"number": 9, "paragraph": "F", "answer": "vi"},
            ],
        },
        {
            "group_id": "mt2_p1_completion_10_13",
            "range": "10-13",
            "question_type": "sentence_completion",
            "instruction": "Complete the sentences below. Choose NO MORE THAN TWO WORDS from the passage for each answer.",
            "word_limit": 2,
            "questions": [
                {"number": 10, "sentence": "Karl von Frisch spent ______ decoding the waggle dance of honeybees.", "answer": "decades", "accepted_answers": ["decades"]},
                {"number": 11, "sentence": "Betty bent a straight piece of ______ into a hook.", "answer": "wire", "accepted_answers": ["wire"]},
                {"number": 12, "sentence": "Scrub jays may move food when other birds are ______.", "answer": "watching", "accepted_answers": ["watching"]},
                {"number": 13, "sentence": "Clever Hans responded to changes in people's ______.", "answer": "posture", "accepted_answers": ["posture", "expression", "posture and expression"]},
            ],
        },
    ],
)

P2 = _payload(
    resource_id="ielts_reading_mt2_passage_2",
    part=2,
    title="The Unfulfilled Promise of Educational Technology",
    passage=PASSAGE_2,
    groups=[
        {
            "group_id": "mt2_p2_tfng_1_5",
            "range": "1-5",
            "question_type": "tfng",
            "instruction": "Do the following statements agree with the information given in the passage?",
            "questions": [
                {"number": 1, "statement": "Thomas Edison predicted that motion pictures would replace textbooks.", "answer": "TRUE"},
                {"number": 2, "statement": "On average only about four per cent of MOOC enrollees completed their courses.", "answer": "TRUE"},
                {"number": 3, "statement": "The 2015 OECD report argued that classroom computers were harmful in themselves.", "answer": "FALSE"},
                {"number": 4, "statement": "Students from poorer backgrounds often use technology mainly for entertainment.", "answer": "TRUE"},
                {"number": 5, "statement": "Benjamin Bloom claimed that one-to-one tutoring could help ninety-eight per cent of pupils outperform their classmates.", "answer": "TRUE"},
            ],
        },
        {
            "group_id": "mt2_p2_headings_6_9",
            "range": "6-9",
            "question_type": "matching_headings",
            "instruction": "The passage has five paragraphs, A–E. Choose the correct heading for paragraphs B–E from the list of headings below.",
            "headings": HEADINGS_2,
            "questions": [
                {"number": 6, "paragraph": "B", "answer": "i"},
                {"number": 7, "paragraph": "C", "answer": "ii"},
                {"number": 8, "paragraph": "D", "answer": "iv"},
                {"number": 9, "paragraph": "E", "answer": "v"},
            ],
        },
        {
            "group_id": "mt2_p2_completion_10_13",
            "range": "10-13",
            "question_type": "sentence_completion",
            "instruction": "Complete the sentences below. Choose NO MORE THAN TWO WORDS from the passage for each answer.",
            "word_limit": 2,
            "questions": [
                {"number": 10, "sentence": "Coursera and edX were launched in ______.", "answer": "2012", "accepted_answers": ["2012"]},
                {"number": 11, "sentence": "Bloom described the tutoring gap as the ______ problem.", "answer": "two sigma", "accepted_answers": ["two sigma"]},
                {"number": 12, "sentence": "The OECD report on school computers was published in ______.", "answer": "2015", "accepted_answers": ["2015"]},
                {"number": 13, "sentence": "The most successful programmes support teachers rather than ______ them.", "answer": "replacing", "accepted_answers": ["replacing", "replace"]},
            ],
        },
    ],
)

P3 = _payload(
    resource_id="ielts_reading_mt2_passage_3",
    part=3,
    title="The Psychology of Leadership in Times of Crisis",
    passage=PASSAGE_3,
    groups=[
        {
            "group_id": "mt2_p3_ynng_1_5",
            "range": "1-5",
            "question_type": "tfng",
            "options_variant": "yes_no",
            "instruction": "Do the following statements agree with the claims of the writer?",
            "questions": [
                {"number": 1, "statement": "Citizens always form an accurate picture of their leaders during a crisis.", "answer": "NO"},
                {"number": 2, "statement": "Stress makes leaders consider a wider range of options.", "answer": "NO"},
                {"number": 3, "statement": "Groupthink was first described using the Bay of Pigs invasion as an example.", "answer": "YES"},
                {"number": 4, "statement": "Roosevelt's broadcasts succeeded because they explained policy in technical detail.", "answer": "NO"},
                {"number": 5, "statement": "Tetlock found that confident forecasts were usually more accurate.", "answer": "NO"},
            ],
        },
        {
            "group_id": "mt2_p3_headings_6_9",
            "range": "6-9",
            "question_type": "matching_headings",
            "instruction": "The passage has five paragraphs, A–E. Choose the correct heading for paragraphs B–E from the list of headings below.",
            "headings": HEADINGS_3,
            "questions": [
                {"number": 6, "paragraph": "B", "answer": "i"},
                {"number": 7, "paragraph": "C", "answer": "iii"},
                {"number": 8, "paragraph": "D", "answer": "iv"},
                {"number": 9, "paragraph": "E", "answer": "v"},
            ],
        },
        {
            "group_id": "mt2_p3_completion_10_14",
            "range": "10-14",
            "question_type": "sentence_completion",
            "instruction": "Complete the sentences below. Choose NO MORE THAN TWO WORDS from the passage for each answer.",
            "word_limit": 2,
            "questions": [
                {"number": 10, "sentence": "Irving Janis introduced the term ______ in 1972.", "answer": "groupthink", "accepted_answers": ["groupthink"]},
                {"number": 11, "sentence": "During the 1930s, ______ broadcast to restore public confidence.", "answer": "Roosevelt", "accepted_answers": ["Roosevelt", "Franklin Roosevelt"]},
                {"number": 12, "sentence": "Tetlock found that bold predictions attracted more ______.", "answer": "trust", "accepted_answers": ["trust", "attention"]},
                {"number": 13, "sentence": "Crises tend to ______ existing personality traits.", "answer": "amplify", "accepted_answers": ["amplify", "exaggerate"]},
                {"number": 14, "sentence": "Sudden changes in a leader's behaviour are often viewed with ______.", "answer": "scepticism", "accepted_answers": ["scepticism", "skepticism"]},
            ],
        },
    ],
)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    files = [
        ("BandForge_Reading_MT2_P1_Interface_Data.json", P1),
        ("BandForge_Reading_MT2_P2_Interface_Data.json", P2),
        ("BandForge_Reading_MT2_P3_Interface_Data.json", P3),
    ]
    for name, payload in files:
        path = OUT / name
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Wrote {path}")


if __name__ == "__main__":
    main()
