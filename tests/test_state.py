from assistant.state import AssistantState, AssistantStatus


def test_state_subscriptions_can_be_removed() -> None:
    state = AssistantState()
    seen = []
    unsubscribe = state.subscribe(seen.append)
    state.set(AssistantStatus.LISTENING)
    state.set(AssistantStatus.LISTENING)
    unsubscribe()
    state.set(AssistantStatus.SLEEPING)
    assert seen == [AssistantStatus.LISTENING]
