from matters.sources.claude_tags import ask_text, command, command_output, message_parts


def test_slash_commands_and_bash_mode() -> None:
    assert command("<command-name>/clear</command-name><command-args></command-args>") == "/clear"
    assert (
        command("<command-name>/model</command-name><command-args>opus</command-args>")
        == "/model opus"
    )
    assert command("<bash-input>ls -la</bash-input>") == "! ls -la"
    assert command("just words") is None


def test_command_output_from_any_stream() -> None:
    assert command_output("<local-command-stdout>ok</local-command-stdout>") == "ok"
    assert command_output("<bash-stdout>a</bash-stdout><bash-stderr>b</bash-stderr>") == "a\nb"
    assert command_output("<local-command-stdout></local-command-stdout>") == ""
    assert command_output("plain") is None


def test_pasted_content_stays_where_it_was_pasted() -> None:
    parts = message_parts(
        'see <pasted_content id="1">a\nb</pasted_content> and fix', has_images=False
    )
    assert [(p.kind, p.text) for p in parts] == [
        ("text", "see"),
        ("pasted", "a\nb"),
        ("text", "and fix"),
    ]
    assert ask_text(parts) == "see [Pasted text · 2 lines] and fix"


def test_injected_context_becomes_labelled_parts() -> None:
    reminder = message_parts("<system-reminder>be brief</system-reminder>", has_images=False)
    notice = message_parts(
        "<task-notification><status>failed</status>"
        "<summary>Build broke</summary></task-notification>",
        has_images=False,
    )
    assert [(p.kind, p.label) for p in reminder + notice] == [
        ("reminder", "System reminder"),
        ("notification", "Build broke"),
    ]


def test_unknown_tags_are_left_as_the_humans_words() -> None:
    assert [
        (p.kind, p.text) for p in message_parts("why is <div> centered?", has_images=False)
    ] == [("text", "why is <div> centered?")]


def test_image_markers_become_image_parts_only_without_real_images() -> None:
    marker = "[Image: original 10x10]\nlook"
    assert [p.kind for p in message_parts(marker, has_images=False)] == ["image", "text"]
    assert [p.kind for p in message_parts(marker, has_images=True)] == ["text"]


def test_closing_tags_may_repeat_their_attributes() -> None:
    parts = message_parts(
        'x <pasted_content id="9">body</pasted_content id="9"> y', has_images=False
    )
    assert [p.kind for p in parts] == ["text", "pasted", "text"]
