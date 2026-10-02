# Stand-in for Workstreams A/B - not part of the Part C deliverable
"""Mail + calendar tools: time words, free time, conflicts, the approval cards and the agent."""

from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from test_loop_agent import ScriptLLM, agent_with, call, reply_text, run

from helpmate.agent import llm_tools
from helpmate.agent.free_time import conflicts, free_slots
from helpmate.agent.tools import default_registry, fmt_span
from helpmate.agent.when import UnclearTime, parse_range, parse_span, parse_when
from helpmate.domain.events import ProposalCreated, ToolResult
from helpmate.domain.models import CalendarEvent, EmailSummary, ProposalStatus, Risk, ToolCall
from helpmate.domain.models import new_id as _id

TZ = ZoneInfo("America/Toronto")
NOW = datetime(2026, 10, 5, 12, 0, tzinfo=TZ)  # Monday noon, as in conftest's clock


def at(day: int, hour: int, minute: int = 0, month: int = 10, year: int = 2026) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=TZ)


def event(title: str, start: datetime, end: datetime) -> CalendarEvent:
    return CalendarEvent(id=_id(), title=title, start=start, end=end)


TUESDAY = [
    event("Standup", at(6, 10), at(6, 11)),
    event("Lunch", at(6, 13, 10), at(6, 14)),
    event("Thanksgiving", at(6, 0), at(7, 0)),  # all day: shown, but never "busy"
]


# --- time words -> periods and event times ---------------------------------------------------


@pytest.mark.parametrize(
    ("words", "start", "end"),
    [
        ("today", at(5, 0), at(6, 0)),
        ("tomorrow afternoon", at(6, 12), at(6, 17)),
        ("tonight", at(5, 17), at(6, 0)),
        ("Friday", at(9, 0), at(10, 0)),
        ("on monday", at(5, 0), at(6, 0)),  # today is Monday
        ("next monday", at(12, 0), at(13, 0)),
        ("this week", at(5, 0), at(12, 0)),  # from today's midnight: earlier events still list
        ("next week", at(12, 0), at(19, 0)),
        ("this weekend", at(10, 0), at(12, 0)),
        ("the next 3 days", at(5, 0), at(9, 0)),
        ("Oct 12", at(12, 0), at(13, 0)),
        ("the 3rd of October", at(3, 0, year=2027), at(4, 0, year=2027)),  # past -> next year
        ("2026-10-20", at(20, 0), at(21, 0)),
    ],
)
def test_parse_range(words, start, end):
    assert parse_range(words, NOW, TZ) == (start, end)


def test_parse_range_rejects_what_it_cant_read():
    with pytest.raises(UnclearTime, match="this week"):
        parse_range("whenever suits", NOW, TZ)


@pytest.mark.parametrize(
    ("words", "start", "end"),
    [
        ("Friday 2 to 4pm", at(9, 14), at(9, 16)),
        ("tomorrow 11-1pm", at(6, 11), at(6, 13)),
        ("tomorrow from 9:30am until 10:15am", at(6, 9, 30), at(6, 10, 15)),
        ("tomorrow at 3pm for 2 hours", at(6, 15), at(6, 17)),
        ("Saturday 10am for half an hour", at(10, 10), at(10, 10, 30)),
        ("tomorrow at 3pm", at(6, 15), None),
        ("Oct 12 at 9:30am", at(12, 9, 30), None),
    ],
)
def test_parse_span(words, start, end):
    assert parse_span(words, NOW, TZ) == (start, end)


def test_parse_span_rejects_a_backwards_range():
    with pytest.raises(UnclearTime, match="ends before"):
        parse_span("tomorrow from 10am to 9am", NOW, TZ)


def test_reminders_understand_calendar_dates_too():
    assert parse_when("on Oct 12 at 5pm", NOW, TZ).due_at == at(12, 17)
    assert parse_when("October 9", NOW, TZ).due_at == at(9, 9)  # a day alone means 09:00


# --- free time and conflicts -----------------------------------------------------------------


def test_free_slots_skip_busy_time_round_to_quarter_hours_and_ignore_all_day_events():
    slots = free_slots(TUESDAY, at(6, 0), at(7, 0), 60, TZ, (9, 18))
    assert slots == [(at(6, 9), at(6, 10)), (at(6, 11), at(6, 13, 10)), (at(6, 14), at(6, 18))]
    longer = free_slots(TUESDAY, at(6, 0), at(7, 0), 90, TZ, (9, 18))
    assert longer == [(at(6, 11), at(6, 13, 10)), (at(6, 14), at(6, 18))]


def test_free_slots_never_start_before_the_given_start():
    slots = free_slots([], at(5, 12, 7), at(6, 0), 60, TZ, (9, 18))
    assert slots == [(at(5, 12, 15), at(5, 18))]


def test_conflicts_are_overlaps_only():
    assert [e.title for e in conflicts(TUESDAY, at(6, 10, 30), at(6, 11, 30), TZ)] == ["Standup"]
    assert conflicts(TUESDAY, at(6, 11), at(6, 12), TZ) == []  # back-to-back is fine


# --- the tools, through the policy engine (fake mail + calendar) -----------------------------


def _call(name: str, **args: object) -> ToolCall:
    return ToolCall(id=_id(), name=name, arguments=args)


async def test_event_card_warns_about_conflicts_and_an_edit_rechecks(container):
    container.calendar.events.extend(TUESDAY)
    outcome = await container.policy.handle_call(
        _call(
            "create_event",
            title="dentist",
            start=at(6, 10, 30).isoformat(),
            end=at(6, 11, 30).isoformat(),
        )
    )
    proposal = outcome.proposal
    assert proposal.risk == Risk.EXTERNAL
    assert proposal.warnings == ["Overlaps Standup, Tue Oct 06 10:00-11:00"]
    assert len(container.calendar.events) == 3  # nothing written yet

    done = await container.policy.decide(
        proposal.id,
        "edit",
        {"title": "dentist", "start": at(6, 15).isoformat(), "end": at(6, 16).isoformat()},
    )
    assert done.status == ProposalStatus.EXECUTED
    assert done.warnings == []
    assert done.summary == "Tue Oct 06 15:00-16:00"
    assert container.calendar.events[-1].title == "dentist"


async def test_email_card_shows_the_whole_message_and_sends_only_on_approval(container):
    outcome = await container.policy.handle_call(
        _call("send_email", to=["jo@example.com"], subject="Running late", body="Hi Jo,\n\n10 min!")
    )
    proposal = outcome.proposal
    assert proposal.title == "Email to jo@example.com"
    assert proposal.preview == "To: jo@example.com\nSubject: Running late\n\nHi Jo,\n\n10 min!"
    assert container.mail.sent == []

    await container.policy.decide(proposal.id, "approve")
    [sent] = container.mail.sent
    assert sent.to == ["jo@example.com"] and sent.body == "Hi Jo,\n\n10 min!"


async def test_invalid_addresses_are_rejected(container):
    outcome = await container.policy.handle_call(
        _call("send_email", to=["not an address"], subject="x", body="y")
    )
    assert not outcome.ok and outcome.proposal is None


async def test_search_email_lists_unread_first_marker_and_snippet(container):
    container.mail.inbox.extend(
        [
            EmailSummary(
                id="1",
                sender="Bank <no-reply@bank.example>",
                subject="Your statement",
                snippet="Statement ready",
                received_at=at(5, 9),
            ),
            EmailSummary(
                id="2",
                sender="Sam",
                subject="Lunch?",
                snippet="",
                received_at=at(4, 18),
                unread=False,
            ),
        ]
    )
    outcome = await container.policy.handle_call(_call("search_email"))
    assert outcome.ok and outcome.proposal is None
    # one sentence to read (or hear); the emails themselves go to the chat as cards
    assert outcome.summary == (
        "Here are 2 emails, 1 unread. The newest is from Bank: Your statement."
    )
    assert [m.id for m in outcome.emails] == ["1", "2"]
    only_sam = await container.policy.handle_call(_call("search_email", query="lunch"))
    assert only_sam.summary == "Here's your latest email, from Sam: Lunch?"  # no "?."
    assert [m.subject for m in only_sam.emails] == ["Lunch?"]


async def test_email_cards_stream_to_the_chat_and_come_back_with_it(client, container):
    container.mail.inbox.append(
        EmailSummary(
            id="m1",
            sender="Sam Lee <sam@example.com>",
            subject="Quick question",
            snippet="Are you free at noon?",
            received_at=at(5, 9),
        )
    )
    container.agent = agent_with(
        container, ScriptLLM(lambda text: "search_email", lambda messages: call("search_email"))
    )
    session = (await client.post("/api/chat/sessions", json={})).json()["id"]
    stream = await client.post(
        f"/api/chat/sessions/{session}/messages", json={"text": "show me the last mail"}
    )
    lines = stream.text.splitlines()
    events = [json.loads(line[len("data: ") :]) for line in lines if line.startswith("data: ")]
    [result] = [e for e in events if e["type"] == "tool.result"]
    assert [(m["id"], m["subject"]) for m in result["emails"]] == [("m1", "Quick question")]

    _, reply = (await client.get(f"/api/chat/sessions/{session}/messages")).json()
    assert reply["text"] == "Here's your latest email, from Sam Lee: Quick question."
    assert [m["snippet"] for m in reply["emails"]] == ["Are you free at noon?"]


async def test_list_events_and_find_free_time(container):
    container.calendar.events.extend(TUESDAY)
    listed = await container.policy.handle_call(
        _call("list_events", start=at(6, 0).isoformat(), end=at(7, 0).isoformat())
    )
    assert listed.summary == (
        "3 events:\n"
        "Tue Oct 06, all day: Thanksgiving\n"
        "Tue Oct 06 10:00-11:00: Standup\n"
        "Tue Oct 06 13:10-14:00: Lunch"
    )
    free = await container.policy.handle_call(
        _call(
            "find_free_time",
            start=at(5, 0).isoformat(),
            end=at(7, 0).isoformat(),
            duration_minutes=120,
        )
    )
    assert free.summary == (
        "Free for 2 h (09:00-18:00):\n"
        "Mon Oct 05 12:00-18:00\n"  # today, from now: the morning has gone
        "Tue Oct 06 11:00-13:10\n"
        "Tue Oct 06 14:00-18:00"
    )


async def test_a_failing_connector_is_reported_not_raised(container):
    async def broken(start, end):
        raise RuntimeError("Google isn't connected yet.")

    container.calendar.list_events = broken
    listed = await container.policy.handle_call(
        _call("list_events", start=at(6, 0).isoformat(), end=at(7, 0).isoformat())
    )
    assert not listed.ok and "Google isn't connected yet." in listed.summary
    card = await container.policy.handle_call(
        _call("create_event", title="x", start=at(6, 9).isoformat(), end=at(6, 10).isoformat())
    )
    assert card.proposal.warnings == ["Couldn't check this first: Google isn't connected yet."]


# --- the model's calls -> canonical args -----------------------------------------------------


def resolve(name: str, said: str | None = None, **arguments):
    return llm_tools.resolve(name, arguments, default_registry(), NOW, TZ, said=said)


def test_search_fields_become_a_gmail_query():
    assert resolve("search_email", sender="bank", unread_only=True, days=7) == {
        "query": "from:bank is:unread newer_than:7d",
        "limit": 5,
    }
    assert resolve("search_email", sender="John Smith", about="field trip")["query"] == (
        'from:"John Smith" field trip'
    )
    assert resolve("search_email")["query"] == ""


def test_email_goes_only_to_addresses_the_owner_typed():
    said = "email jo@example.com to say I'll be late"
    args = resolve("send_email", said, to=["joe@example.com"], subject="Late", body="Hi")
    assert args["to"] == ["jo@example.com"]  # the model's typo is replaced by what was typed
    with pytest.raises(llm_tools.NeedsOwner, match="email address"):
        resolve("send_email", "email mom to say hi", to=["mom@example.com"], subject="Hi", body="x")
    # without the owner's words (e.g. an eval harness) the model's addresses are used as given
    assert resolve("send_email", to="a@b.co", subject="s", body="b")["to"] == ["a@b.co"]


def test_event_time_words_are_resolved_in_code():
    args = resolve("create_event", title="gym", when="Saturday 10 to 11:30am")
    assert (args["start"], args["end"]) == (
        at(10, 10).isoformat(),
        at(10, 11, 30).isoformat(),
    )
    short = resolve("create_event", title="call", when="tomorrow at 3pm", duration_minutes=30)
    assert short["end"] == at(6, 15, 30).isoformat()
    default = resolve("create_event", title="call", when="tomorrow at 3pm")
    assert default["end"] == at(6, 16).isoformat()
    with pytest.raises(llm_tools.ResolveError, match="create_event"):
        resolve("create_event", title="x", when="sometime")


def test_periods_have_sensible_defaults():
    assert resolve("list_events") == {"start": at(5, 0).isoformat(), "end": at(6, 0).isoformat()}
    free = resolve("find_free_time", when="next week", duration_minutes=120)
    assert free == {
        "start": at(12, 0).isoformat(),
        "end": at(19, 0).isoformat(),
        "duration_minutes": 120,
    }


# --- the agent --------------------------------------------------------------------------------


async def test_agent_asks_for_an_address_instead_of_inventing_one(container):
    llm = ScriptLLM(
        lambda text: "send_email",
        lambda messages: call(
            "send_email", to=["mom@example.com"], subject="Late", body="Running late"
        ),
    )
    events = await run(agent_with(container, llm), "email mom that I'm running late")
    assert not any(isinstance(e, ProposalCreated) for e in events)
    assert "email address" in reply_text(events)
    assert len(llm.calls) == 2  # route + one tool call: no retry, only the owner can fix this


async def test_agent_event_card_mentions_the_conflict(container):
    container.calendar.events.extend(TUESDAY)
    llm = ScriptLLM(
        lambda text: "create_event",
        lambda messages: call("create_event", title="dentist", when="tomorrow at 10:30am"),
    )
    events = await run(
        agent_with(container, llm), "put the dentist on my calendar tomorrow 10:30am"
    )
    [card] = [e.proposal for e in events if isinstance(e, ProposalCreated)]
    assert card.warnings == ["Overlaps Standup, Tue Oct 06 10:00-11:00"]
    assert "Heads up: Overlaps Standup" in reply_text(events)
    # the routed call saw only create_event's rules
    system = llm.calls[1]["messages"][0].content
    assert "create_event" in system and "create_reminder" not in system


async def test_agent_answers_calendar_questions_from_the_calendar(container):
    container.calendar.events.extend(TUESDAY)
    llm = ScriptLLM(
        lambda text: "list_events", lambda messages: call("list_events", when="tomorrow")
    )
    events = await run(agent_with(container, llm), "what's on tomorrow?")
    [result] = [e for e in events if isinstance(e, ToolResult)]
    assert result.ok and "Standup" in result.summary
    assert reply_text(events) == result.summary


def test_period_labels_read_naturally():
    assert fmt_span(at(5, 0), at(12, 0), TZ) == "Mon Oct 05 - Sun Oct 11"
    assert fmt_span(at(5, 0), at(6, 0), TZ) == "Mon Oct 05"
    assert fmt_span(at(5, 12), at(12, 0), TZ) == "Mon Oct 05 12:00 - Sun Oct 11"
    assert fmt_span(at(5, 22), at(6, 1), TZ) == "Mon Oct 05 22:00 - Tue Oct 06 01:00"


# --- routing guard + list_tasks (live miss Sep 30: "show me the last mail" -> list_reminders) -----


def test_reminder_routes_need_a_reminder_word():
    for text in ("show me the last mail", "show me my tasks", "what's on Friday?"):
        routes = llm_tools.routes_for(text)
        assert "list_reminders" not in routes and "create_reminder" not in routes
        assert "list_reminders" not in llm_tools.router_prompt(routes)
        assert llm_tools.route_format(routes)["properties"]["action"]["enum"] == list(routes)
    assert "list_reminders" in llm_tools.routes_for("any reminders coming up?")
    assert "create_reminder" in llm_tools.routes_for("Remind me to stretch at 5")
    assert llm_tools.parse_route('{"action": "list_reminders"}', ("reply", "search_email")) == (
        "reply"
    )


async def test_agent_router_is_not_offered_reminders_for_a_mail_question(container):
    llm = ScriptLLM(lambda text: "search_email", lambda messages: call("search_email"))
    await run(agent_with(container, llm), "show me the last mail")
    router = llm.calls[0]
    assert "list_reminders" not in router["schema"]["properties"]["action"]["enum"]
    assert "list_reminders" not in router["messages"][0].content


async def test_list_tasks_groups_open_tasks_by_horizon(container):
    for title, horizon in (("read ch. 3", "term"), ("buy milk", "week"), ("learn Go", "someday")):
        await container.policy.handle_call(_call("create_task", title=title, horizon=horizon))
    for proposal in await container.repos.proposals.find():
        await container.policy.decide(proposal.id, "approve")
    everything = await container.policy.handle_call(_call("list_tasks"))
    assert everything.summary == (
        "3 open tasks:\nThis week: buy milk\nThis term: read ch. 3\nSomeday: learn Go"
    )
    term = await container.policy.handle_call(_call("list_tasks", horizon="term"))
    assert term.summary == "1 open task for this term:\nThis term: read ch. 3"
    assert resolve("list_tasks", horizon="this term") == {"horizon": "term"}
    assert resolve("list_tasks", horizon="all") == {"horizon": None}


def test_task_and_mail_routes_need_their_topic_words():
    explain = llm_tools.routes_for("Explain the PARA method for organizing notes")
    assert "create_task" not in explain and "list_tasks" not in explain
    assert "search_email" not in explain and "send_email" not in explain
    assert {"list_tasks", "create_task"} <= set(llm_tools.routes_for("show me my to-do list"))
    assert "send_email" in llm_tools.routes_for("write to sam.lee@example.com, say thanks")
    assert "search_email" in llm_tools.routes_for("check my inbox")
    assert "list_events" in llm_tools.routes_for("am I free Friday?")  # calendar: never guarded


def test_placeholder_strings_mean_not_given():
    # live Sep 30: llama3.2:3b sent sender="null", about="null" -> Gmail searched `from:null null`
    assert resolve("search_email", sender="null", about="None", days="n/a")["query"] == ""
    event = resolve("create_event", title="gym", when="Saturday at 10am", location="null")
    assert event["location"] is None
