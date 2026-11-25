"""Hours shown as clock time: 5.5 is 5h 30min, 0.75 is 45 min."""


def text(hours):
    try:
        number = float(hours)
    except (TypeError, ValueError):
        return ""
    minutes = int(round(abs(number) * 60.0))
    sign = "-" if number < 0 and minutes else ""
    whole, mins = divmod(minutes, 60)
    if whole == 0:
        return sign + "%d min" % mins
    if mins == 0:
        return sign + "%dh" % whole
    return sign + "%dh %dmin" % (whole, mins)
