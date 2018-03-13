from abc import *
import logging
import os.path as osp
import sys
from typing import List

import discord
from discord import utils

logger = logging.getLogger('dd-bot')


# Exceptions
class ColourCodeParseError(ValueError):
    def __init__(self, msg, linenum):
        self.linenum = linenum
        super(ColourCodeParseError, self).__init__(msg)

    def __str__(self):
        return f"At line [{self.linenum}]: " + super(ColourCodeParseError, self).__str__()


# Data Class
class Ranklike(ABC):
    @staticmethod
    async def realize(self, role_creator):
        pass

    @staticmethod
    @abstractstaticmethod
    def from_json(server, ent):
        pass

    @abstractmethod
    def to_json(self):
        pass


class Rank(Ranklike):
    JSON_TYPE_MARKER = 'r'

    def __init__(self, name, colour):
        self.name = name
        self.colour = colour

    async def realize(self, role_creator):
        self.role = await role_creator(self.name, self.colour)

    @staticmethod
    def from_json(server, ent):
        return RealizedRank(server, ent['id'])

    def to_json(self):
        raise RuntimeError("Trying to serizlize unrealized rank")


class RealizedRank(Ranklike):
    JSON_TYPE_MARKER = 'r'

    def __init__(self, server: discord.Server, _id):
        self.role = utils.get(lambda role: role.id == _id, server.roles)

    def realize(self, _):
        pass

    @staticmethod
    def from_json(server, ent):
        return RealizedRank(server, ent['id'])

    def to_json(self):
        return {"type": self.JSON_TYPE_MARKER, "name": self.role.name,
                "id": self.role.id}


class UnorderedRankGroup(Ranklike):
    JSON_TYPE_MARKER = 'ug'

    def __init__(self, name, ranks):
        self.name = name
        self.ranks = ranks

    async def realize(self, role_creator):
        for r in self.ranks:
            r.realize(role_creator)

    @staticmethod
    def from_json(server, ent):
        return UnorderedRankGroup(ent['name'], [RealizedRank(server, r['id']) for r in ent['ranks']])

    def to_json(self):
        return {"type": self.JSON_TYPE_MARKER, "name": self.name,
                "ranks": [r.toJson() for r in self.ranks]}


class OrderedRankGroup(UnorderedRankGroup):
    JSON_TYPE_MARKER = 'og'

    def __init__(self, name: str, ranks: List[Ranklike], realized: bool = False):
        super(OrderedRankGroup, self).__init__(name, ranks)
        self._realized = realized

    async def realize(self, role_creator):
        if not self._realized:
            self.ranks += self.ranks
            super(OrderedRankGroup, self).realize(role_creator)
            self._realized = True

    @staticmethod
    def from_json(server, ent):
        return OrderedRankGroup(ent['name'], [RealizedRank(server, r['id']) for r in ent['ranks']], realized=True)


# Data structure to store Ranks
class RankRegistry(object):
    clazz = {cls.JSON_TYPE_MARKER: cls for cls in [Rank, OrderedRankGroup, UnorderedRankGroup]}

    def __init__(self, a_map):
        self._map = a_map

    @classmethod
    def from_definition(cls, def_path, client):
        if not osp.exists(def_path):
            logger.error(f"Rank definition file {def_path} not found! Shutting down now...")
            sys.exit(0)
        return cls(RankRegistry._read_ranks(def_path))

    @classmethod
    def from_json(cls, obj):
        if type(obj) is not list:
            raise ValueError("JSON file does not contain a list of objects.")
        res = {entry['name']: cls.clazz[entry['type']].from_json(entry) for entry in obj}
        return cls(res)

    def to_json(self):
        return [e.to_json for e in self._map.values()]

    @staticmethod
    def _read_ranks(path):
        """pre-condition: path exists"""
        def parse_rank(i, rank):
            name, color = tuple(map(str.strip, rank.split(',')))
            if color == 'None':
                color = discord.Colour.default()
            elif color.startswith('#'):
                try:
                    hexcode = int(color[1:], base=16)
                    if hexcode > 0xFFFFFF:
                        raise ColourCodeParseError(f"Invalid hex value \"{color}\", "
                                                   "value must be between #0000 and #ffffff", i)
                    color = discord.Colour(hexcode)
                except ColourCodeParseError as ex:
                    raise ex
                except ValueError:
                    raise ColourCodeParseError(f"Invalid hex code \"{color}\"", i)
            else:
                raise ColourCodeParseError(f"Unrecognized color format \"{color}\"", i)
            return Rank(name, color)

        try:
            with open(path) as rank_file:
                raise NotImplementedError()

        except Exception as ex:
            logger.error(ex)
            sys.exit(0)
