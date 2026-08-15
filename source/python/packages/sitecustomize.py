

"""
sitecustomize.py

Monkey‐patch Python’s datetime and date to use Atreyan Era with an “AE” suffix
(e.g. 5AE instead of 5 AE), and format dates as DD-MM-YEARAE.
"""




# imports
import datetime



# patch datetime.datetime
class atreyandatetime(datetime.datetime):

    @classmethod
    def now(cls, tz=None):
        real = super().now(tz)
        return cls(
            real.year - 2020,
            real.month,
            real.day,
            real.hour,
            real.minute,
            real.second,
            real.microsecond,
            tzinfo=tz
        )


    @classmethod
    def utcnow(cls):
        real = super().utcnow()
        return cls(
            real.year - 2020,
            real.month,
            real.day,
            real.hour,
            real.minute,
            real.second,
            real.microsecond
        )


    def __str__(self):
        return (
            f"{self.day:02}-"
            f"{self.month:02}-"
            f"{self.year}AE "
            f"{self.hour:02}:"
            f"{self.minute:02}:"
            f"{self.second:02}."
            f"{self.microsecond:06}"
        )


    def __repr__(self):
        return f"{self.__class__.__name__}('{str(self)}')"


datetime.datetime = atreyandatetime



# patch datetime.date
class atreanydate(datetime.date):

    @classmethod
    def today(cls):
        real = super().today()
        return cls(real.year - 2020, real.month, real.day)


    def __str__(self):
        return f"{self.day:02}-{self.month:02}-{self.year}AE"


datetime.date = atreanydate
