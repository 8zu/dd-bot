import asyncio
import logging
import os.path as osp
import sys
import random
from collections import namedtuple

import pytoml

from cache import Cache

Command = namedtuple('Command', ['rank', 'add'])

try:
    from discord.ext import commands
    from discord import utils
    import discord
except ImportError:
    print("Discord.py is not installed.\n"
          "Consult the guide for your operating system "
          "and do ALL the steps in order.\n"
          "https://twentysix26.github.io/Red-Docs/\n")
    sys.exit(1)

config_path = './config.toml'
description = """A simple mod bot"""

logging.basicConfig(level=logging.INFO)
handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w')
handler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))
logger = logging.getLogger('borderbot')
logger.addHandler(handler)

def get_config(path):
    if osp.exists(path):
        config = pytoml.load(open(path, "r", encoding="UTF-8"))
    else:
        logger.error("Missing config file! Shutting down now...")
        sys.exit(1)

    return config

RoleAssignment = namedtuple("RoleAssignment", ['name', 'color'])

class ColourCodeParseError(ValueError):
    def __init__(self, msg, linenum):
        self.linenum = linenum
        super(ColourCodeParseError, self).__init__(msg)

    def __str__(self):
        return f"At line [{self.linenum}]: " + super(ColourCodeParseError, self).__str__()

def read_ranks(path):
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
        return RoleAssignment(name, color)

    if osp.exists(path):
        try:
            with open(path) as ranks:
                return [parse_rank(linenum+1, rank)
                        for linenum, rank in enumerate(ranks)]
        except Exception as ex:
            logger.error(ex)
            sys.exit(1)
    else:
        logger.error("Missing rank file! Shutting down now...")
        sys.exit(1)

class NotJoinedServerException(Exception):
    pass

class MissingPermissionError(Exception):
    pass

class DesignatedChannelNotFoundException(Exception):
    pass

class DDBot(commands.Bot):
    def __init__(self, cache, texts, ranks):
        super().__init__(description=description, command_prefix='+')
        self.cache = cache
        self.texts = texts
        self.ranks = ranks
        self.initialized = False

    def is_me(self, author):
        return author == self.user

    def is_owner(self, author):
        return self.server and author == self.server.owner

    def is_command(self, cmd, s):
        return s.strip().split(' ')[0] == f"{self.command_prefix}{cmd}"

    def like_command(self, cmd, s):
        return s.strip().split(' ')[0].startswith(f"{self.command_prefix}{cmd}")

    def find_role(self, name):
        roles = self.server.role_hierarchy
        return utils.find(lambda r: r.name == name, roles)

    def find_channel(self, name):
        return utils.find(lambda ch: ch.name == name, self.get_all_channels())

    def resume(self, cache, config):
        if self.initialized:
            return

        self.server = cache.load('server.json').get_or(None)
        if not self.server:
            logger.info("The bot has not joined a server, initialization incomplete")
            raise NotJoinedServerException()
        self.server = self.get_server(self.server)
        self.member = self.server.get_member(self.user.id)

        perm = self.member.server_permissions
        if not perm.read_messages or not perm.manage_roles:
            raise MissingPermissionError()

        self.main_channel = self.find_channel(config['bot_channel'])
        if not self.main_channel:
            raise DesignatedChannelNotFoundException()

        self.ranks = read_ranks(config['ranks_path'])

        logger.info("Initialization complete")
        self.initialized = True
        return

    async def createRanks(self):
        """After resume()"""
        if not hasattr(self, "ranks"):
            raise RuntimeError("ranks have not been populated")
        logger.info("creating ranks...")
        for ra in self.ranks:
            await self.create_role(self.server, name=ra.name, colour=ra.color)
        logger.info("ranks are created!")

    def parse_command(self, s):
        if s[0] in ['+', '-']:
            return Command(s[1:], s[0] == '+')
        else:
            None

    async def cleanup_after(self, reply, member):
        await self.delete_messages([reply, *self.vetting_room[member.id]])

    async def add_rank(self, user, rank):
        await self.add_roles(user, self.find_role(rank))

    async def remove_rank(self, user, rank):
        await self.remove_roles(user, self.find_role(rank))

def initialize(config):
    cache = Cache(config['cache_root'])
    texts = get_config(config['text_path'])
    ranks = read_ranks(config['ranks_path'])
    bot = DDBot(cache, texts, ranks)

    @bot.event
    async def on_ready():
        try:
            bot.resume(cache, config)
        except MissingPermissionError:
            logger.error("I don't have some required permission. Please fix")
        except DesignatedChannelNotFoundException:
            logger.error(f"The designated channel \"{config['bot_channel']}\" does not exist."
                        "This bot will not do anything. Please fix.")
        except NotJoinedServerException:
            return

        if bot.initialized:
            print(f'Server: {bot.server.name}')
            print(f'Bot channel: #{bot.main_channel.name}')
            print()
            print('Available ranks:')
            for rank in bot.ranks[:5]:
                print(f"\t{rank.name}, {rank.color.to_tuple()}")
            if len(bot.ranks) > 5:
                print(f"... {len(bot.ranks)} in total")

    @bot.event
    async def on_server_join(server):
        logger.info(f"I joined server {server.name}")
        cache.save("server.json", server.id)
        try:
            bot.resume(cache, config)
        except MissingPermissionError:
            logger.error("I don't have some required permission. Leaving now...")
            await bot.leave_server(server)
            cache.purge("server.json")
        except DesignatedChannelNotFoundException:
            logger.error(f"The designated channel \"{config['bot_channel']}\" does not exist."
                        "This bot will not do anything. Please fix.")
        except NotJoinedServerException:
            logger.error("Unexpected NotJoinedServerException thrown in on_server_join")

        await bot.createRanks()

    @bot.event
    async def on_server_remove(server):
        logger.info(f"I am kicked from server {server.name}")
        cache.purge('server.json')

    @bot.event
    async def on_message(msg):
        if bot.is_me(msg.author):
            return
        if not bot.initialized:
            return

        async def say(msg_id, **kwargs):
            return await bot.send_message(msg.channel, texts[msg_id].format(**kwargs))

        if msg.channel == bot.main_channel:
            cmd = bot.parse_command(msg.content)
            if not cmd or not cmd.rank:
                return
            if cmd.rank in bot.ranks:
                if cmd.add:
                    await bot.add_rank(msg.author, cmd.rank)
                    await say('add_rank_response', user=msg.author.id, rank=cmd.rank)
                else:
                    await bot.remove_rank(msg.author, cmd.rank)
                    await say('remove_rank_response', user=msg.author.id, rank=cmd.rank)
            else:
                await say('rank_not_found')

    return bot

if __name__ == '__main__':
    config = get_config(config_path)
    if 'token' not in config or not config['token']:
        logger.error("Token is not filled in! Shutting down now...")
        sys.exit(1)
    bot = initialize(config)
    bot.run(config['token'])
