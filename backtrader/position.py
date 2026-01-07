#!/usr/bin/env python
# -*- coding: utf-8; py-indent-offset:4 -*-
"""Position Module - Position tracking and management.

This module provides the Position class for tracking the size and price
of trading positions. It maintains position state including opening
and closing amounts.

Classes:
    Position: Tracks position size, price, and related attributes.

Example:
    Getting position from broker:
    >>> position = broker.getposition(data)
    >>> print(f"Size: {position.size}, Price: {position.price}")
"""


# Position class, keeps and updates position size and price, has no relationship with any other assets, only keeps size and price
class Position(object):
    """Keeps and updates the size and price of a position.

    The Position object has no relationship to any specific asset. It only
    keeps size and price information.

    Attributes:
        size: Current position size (positive for long, negative for short).
        price: Current price of the position.
        price_orig: Original price when position was opened.
        upopened: Amount of position opened in last update.
        upclosed: Amount of position closed in last update.
        adjbase: Adjustment base for position calculations.

    Example:
        >>> position = Position(size=100, price=50.0)
        >>> print(len(position))  # Returns True if size != 0
    """

    # Information displayed when printing position
    def __str__(self):
        return (
            "--- Position Begin\n"
            f"- Size: {self.size}\n"
            f"- Price: {self.price}\n"
            f"- Price orig: {self.price_orig}\n"
            f"- Closed: {self.upclosed}\n"
            f"- Opened: {self.upopened}\n"
            f"- Adjbase: {self.adjbase}\n"
            "--- Position End"
        )

    # Initialize based on different size and price
    def __init__(self, size=0, price=0.0):
        self.datetime = None
        self.size = size
        if size:
            self.price = self.price_orig = price
        else:
            self.price = 0.0

        self.adjbase = None

        self.upopened = size
        self.upclosed = 0
        self.set(size, price)

        self.updt = None

    # Modify position's size and price
    def fix(self, size, price):
        oldsize = self.size
        self.size = size
        self.price = price
        return self.size == oldsize

    # Set position's size and price
    def set(self, size, price):
        # If current position > 0 and theoretical size > current size, means new position opening;
        # If theoretical size <= current position, opening amount is minimum of 0 and theoretical size;
        # Closing amount equals minimum of current position and current position minus theoretical position
        if self.size > 0:
            if size > self.size:
                self.upopened = size - self.size  # new 10 - old 5 -> 5
                self.upclosed = 0
            else:
                # same side min(0, 3) -> 0 / reversal min(0, -3) -> -3
                self.upopened = min(0, size)
                # same side min(10, 10 - 5) -> 5
                # reversal min(10, 10 - -5) -> min(10, 15) -> 10
                self.upclosed = min(self.size, self.size - size)
        # Similar effect when current position < 0
        elif self.size < 0:
            if size < self.size:
                self.upopened = size - self.size  # ex: -5 - -3 -> -2
                self.upclosed = 0
            else:
                # same side max(0, -5) -> 0 / reversal max(0, 5) -> 5
                self.upopened = max(0, size)
                # same side max(-10, -10 - -5) -> max(-10, -5) -> -5
                # reversal max(-10, -10 - 5) -> max(-10, -15) -> -10
                self.upclosed = max(self.size, self.size - size)
        # If current position equals 0, both new opening and closing equal 0
        # todo Using 0 directly instead of self.size may improve efficiency
        else:  # self.size == 0
            self.upopened = self.size
            self.upclosed = 0
        # Actual position size
        self.size = size
        # Original price
        self.price_orig = self.price
        # If position size > 0, current price equals price, otherwise current price equals 0
        if size:
            self.price = price
        else:
            self.price = 0.0

        return self.size, self.price, self.upopened, self.upclosed

    # When calling len(position), return absolute value of position
    def __len__(self):
        return abs(self.size)

    # When calling bool(position), check if current size equals 0
    def __bool__(self):
        return bool(self.size != 0)

    __nonzero__ = __bool__

    # Clone position information
    def clone(self):
        return Position(size=self.size, price=self.price)

    # Create a position instance, then update size and price
    def pseudoupdate(self, size, price):
        return Position(self.size, self.price).update(size, price)

    # Update size and price
    def update(self, size, price, dt=None):
        """
        Updates the current position and returns the updated size, price and
        units used to open/close a position
        # Update current position and return updated size, price and position size needed to open/close

        Args:
            size (int): amount to update the position's size
                if size < 0: A sell operation has taken place
                if size > 0: A buy operation has taken place
            # Amount to update position size, if size < 0, a sell operation will be executed, if size > 0, a buy operation will be executed
            price (float):
                Must always be positive to ensure consistency
            # Price, must always be positive to maintain consistency
            dt (datetime.datetime): record datetime update (datetime.datetime)

        Returns:

            A tuple (non-named) contaning
               size - new position size
                   Simply the sum of the existing size plus the "size" argument
               price - new position price
                   If a position is increased, the new average price will be
                   returned
                   If a position is reduced, the price of the remaining size
                   does not change
                   If a position is closed,  the price is nullified
                   If a position is reversed, the price is the price given as
                   argument
               opened - amount of contracts from argument "size" that were used
                   to open/increase a position.
                   A position can be opened from 0 or can be a reversal.
                   If a reversal is performed, then opened is less than "size",
                   because part of "size" will have been used to close the
                   existing position
               closed - the amount of units from arguments "size" that were used to
                   close/reduce a position

            Both opened and closed carry the same sign as the "size" argument
            because they refer to a part of the "size" argument
            # Result will return a tuple containing the following data:
            # size represents new position size, simply existing position size plus new position increment
            # price represents new position price, returns different price based on different position
            # opened represents position size to be newly opened
            # closed represents position size to be closed
        """
        # Update position time
        self.datetime = dt  # record datetime update (datetime.datetime)
        # Original price
        self.price_orig = self.price
        # Old position size
        oldsize = self.size
        # New position size
        self.size += size
        # If size is 0
        if not self.size:
            # Update closed existing position
            # Update opening, closing and price
            opened, closed = 0, size
            self.price = 0.0
        # If position size is 0, need to open size amount
        elif not oldsize:
            # Update opened a position from 0
            opened, closed = size, 0
            self.price = price
        # If original position size is 0
        elif oldsize > 0:  # existing "long" position updated
            # If increased position > 0, need new opening, and calculate average position price
            if size > 0:  # increased position
                opened, closed = size, 0
                self.price = (self.price * oldsize + size * price) / self.size
            # If after closing size, position still > 0, close size
            elif self.size > 0:  # reduced position
                opened, closed = 0, size
                # self.price = self.price
            # In other cases, need to open self.size, close -oldsize
            else:  # self.size < 0 # reversed position form plus to minus
                opened, closed = self.size, -oldsize
                self.price = price
        # Original position is negative
        else:  # oldsize < 0 - existing short position updated
            # If newly added position is also negative, open size
            if size < 0:  # increased position
                opened, closed = size, 0
                self.price = (self.price * oldsize + size * price) / self.size
            # If current self.size < 0, close size
            elif self.size < 0:  # reduced position
                opened, closed = 0, size
                # self.price = self.price
            # In other cases, need to open self.size, close -oldsize
            else:  # self.size > 0 - reversed position from minus to plus
                opened, closed = self.size, -oldsize
                self.price = price
        # Opening and closing amounts
        self.upopened = opened
        self.upclosed = closed

        return self.size, self.price, opened, closed
