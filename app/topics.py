from dataclasses import dataclass


@dataclass(frozen=True)
class Topic:
    id: str
    title: str
    title_tr: str
    scenario: str


TOPICS: list[Topic] = [
    Topic("small-talk", "Small talk", "Günlük sohbet",
          "A relaxed chat about the learner's day, hobbies and plans, like two friends catching up."),
    Topic("job-interview", "Job interview", "İş görüşmesi",
          "Role-play: you are an interviewer at a tech company and the learner is the candidate. "
          "Ask typical interview questions one at a time."),
    Topic("travel", "Travel & holidays", "Seyahat ve tatil",
          "Talk about past trips and dream destinations; occasionally role-play situations like "
          "checking in at a hotel or asking for directions."),
    Topic("restaurant", "At a restaurant", "Restoranda",
          "Role-play: you are a waiter and the learner is a customer ordering food, asking about "
          "the menu and paying the bill."),
    Topic("work-meeting", "Work meeting", "İş toplantısı",
          "Role-play a team meeting: discuss project status, deadlines and problems. The learner "
          "should explain their work and give opinions."),
    Topic("technology", "Technology", "Teknoloji",
          "Discuss technology, software, AI and how they affect daily life and work."),
    Topic("movies-books", "Movies & books", "Film ve kitaplar",
          "Talk about favourite movies, series and books; ask the learner to describe plots and give opinions."),
    Topic("doctor", "At the doctor", "Doktorda",
          "Role-play: you are a doctor and the learner is a patient describing symptoms."),
    Topic("opinions", "Debate & opinions", "Tartışma ve fikirler",
          "Pick a light debate topic (e.g. remote work vs office) and ask the learner to argue and "
          "justify their opinion. Politely challenge their points."),
]

TOPICS_BY_ID = {t.id: t for t in TOPICS}
