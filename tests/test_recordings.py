from blaster.recordings import recording_filename, safe_recording_path


def test_recording_name_contains_credit_phone_and_local_datetime(tmp_path):
    name = recording_filename(
        {"credit_id": "CRÉD/001 A", "phone": "+52 (55) 1234-5678"},
        "2026-09-04T20:53:02.330000+00:00",
        "America/Mexico_City",
    )

    assert name == "CRED-001-A_525512345678_20260904_145302_330.ogg"
    assert safe_recording_path(tmp_path, name) == tmp_path / name


def test_recording_path_rejects_traversal_and_symlinks(tmp_path):
    outside = tmp_path.parent / "outside.ogg"
    outside.write_bytes(b"audio")
    link = tmp_path / "linked.ogg"
    link.symlink_to(outside)

    assert safe_recording_path(tmp_path, "../../outside.ogg") is None
    assert safe_recording_path(tmp_path, "audio.wav") is None
    assert safe_recording_path(tmp_path, link.name) is None
