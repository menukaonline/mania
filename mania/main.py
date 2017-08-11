import cursor
import requests
import progress.bar
import argparse
import os
import sys
import whaaaaat

import eyed3
eyed3.log.setLevel("ERROR")

from mania import authentication
from mania import constants

def log(config, message=""):
	if config["quiet"]:
		return
	print(message)

def sanitize(string):
	illegal_symbols = ["/"]
	return "".join([symbol for symbol in string
	                if symbol not in illegal_symbols])

def search(client, config, media_type, query):
	log(config, "Searching...")
	string = " ".join(query)
	search = client.search(string, config["search-count"])
	results = search[f"{media_type}_hits"]
	if not results:
		log(config, "No results found.")
		sys.exit(2)
	if config["lucky"]:
		return results[0]
	def song_handler(results):
		choices = []
		for result in results:
			title = result["track"]["title"]
			artist = result["track"]["artist"]
			album = result["track"]["album"]
			year = result["track"]["year"]
			label = f"{title}\n      {artist}\n      {album} ({year})\n"
			choices.append({"name": label, "value": result, "short": title})
		return choices
	def album_handler(results):
		choices = []
		for result in results:
			name = result["album"]["name"]
			artist = result["album"]["artist"]
			year = result["album"]["year"]
			label = f"{name} ({year})\n      {artist}\n"
			choices.append({"name": label, "value": result, "short": name})
		return choices
	def artist_handler(results):
		choices = []
		for result in results:
			name = result["artist"]["name"]
			label = name
			choices.append({"name": label, "value": result, "short": name})
		return choices
	media_handlers = {"song": song_handler,
	                  "album": album_handler,
	                  "artist": artist_handler}
	choices = media_handlers[media_type](results)
	questions = [{"type": "list",
	              "name": "choice",
                  "message": "Select one:",
                  "choices": choices}]
	answer = whaaaaat.prompt(questions)
	if "choice" not in answer:
		sys.exit(1)
	return answer["choice"]

def song(client, config, query):
	song_object = search(client, config, "song", query)
	song_title = sanitize(song_object["track"]["title"])
	song_id = song_object["track"]["storeId"]

	path = "/".join([config["output-directory"], song_title])
	download_song(client, config, song_object["track"], path)
	log(config, "Done!")

def download_song(client, config, song_object, song_path):
	temporary_path = ".".join([song_path, constants.temporary_extension])
	final_path = ".".join([song_path, constants.final_extension])
	if os.path.isfile(final_path):
		log(config, f"Skipping {os.path.basename(final_path)}; it already exists.")
		return
	song_id = song_object["storeId"]
	if config["increment-playcount"]:
		client.increment_song_playcount(song_object["storeId"])
	stream_url = client.get_stream_url(song_id, quality=config["quality"])
	os.makedirs(os.path.dirname(final_path), exist_ok=True)
	request = requests.get(stream_url, stream=True)
	request.raise_for_status()
	with open(temporary_path, mode="wb") as pointer:
		chunk_size = 4096
		length = int(request.headers.get("content-length")) / chunk_size
		bar = None
		if not config["quiet"]:
			bar = progress.bar.IncrementalBar(os.path.basename(final_path),
			                                  max=length,
			                                  suffix="%(percent).f%%")
		for chunk in request.iter_content(chunk_size=chunk_size):
			pointer.write(chunk)
			if bar:
				bar.next()
		log(config)
	if not config["skip-metadata"]:
		log(config, "Resolving metadata...")
		request = requests.get(song_object["albumArtRef"][0]["url"])
		file = eyed3.load(temporary_path)
		file.initTag()
		file.tag.title = song_object["title"]
		file.tag.artist = song_object["artist"]
		file.tag.album = song_object["album"]
		file.tag.album_artist = song_object["albumArtist"]
		file.tag.track_num = song_object["trackNumber"]
		file.tag.genre = song_object["genre"]
		file.tag.images.set(3, request.content, "image/jpeg")
		file.tag.save()
	os.rename(temporary_path, final_path)

def album(client, config, query):
	lite_album_object = search(client, config, "album", query)
	album_id = lite_album_object["album"]["albumId"]
	album_object = client.get_album_info(album_id, include_tracks=True)
	album_title = sanitize(album_object["name"])
	path = "/".join([config["output-directory"], album_title])
	download_album(client, config, album_object, path)

def download_album(client, config, album_object, album_path):
	total_count = len(album_object['tracks'])
	for index, song_object in enumerate(album_object["tracks"]):
		song_title = sanitize(song_object["title"])
		song_id = song_object["storeId"]
		padding = constants.track_digit_padding
		song_track_number = str(song_object["trackNumber"]).zfill(padding)
		song_file_name = f"{song_track_number} - {song_title}"
		song_path = "/".join([album_path, song_file_name])
		log(config, f"Downloading {index + 1} of {total_count} songs...")
		# numbering starts at zero, Dijkstra said, it'll be better, he said
		download_song(client, config, song_object, song_path)

def discography(client, config, query):
	log(config, "searching")
	lite_artist_object = search(client, config, "artist", query)
	artist_id = lite_artist_object["artist"]["artistId"]
	artist_object = client.get_artist_info(artist_id,
	                                       include_albums=True,
	                                       max_top_tracks=0,
	                                       max_rel_artist=0)
	artist_name = sanitize(artist_object["name"])
	total_count = len(artist_object['albums'])
	for index, lite_album_object in enumerate(artist_object["albums"]):
		album_id = lite_album_object["albumId"]
		album_object = client.get_album_info(album_id, include_tracks=True)
		album_title = sanitize(album_object["name"])
		path = "/".join([config["output-directory"], artist_name, album_title])
		log(config, f"Downloading {index + 1} of {total_count} albums...")
		download_album(client, config, album_object, path)

def load_config(args):
	def initialize(config_file):
		config_file = constants.config_file
		if not os.path.isfile(config_file):
			os.makedirs(os.path.dirname(config_file), exist_ok=True)
			with open(config_file, "w") as config_pointer:
				constants.yaml.dump(constants.default_config, config_pointer)
		return config_file
	config_file = args["config_file"] or initialize(constants.default_config)
	with open(config_file) as config_pointer:
		file = constants.yaml.load(config_pointer) or {}
		# why does argparse have to replace hyphens with underscores?
		# both are valid in the context of dictionary keys
		config = {key: args.get(key.replace("-", "_")) or file.get(key) or value
		          for key, value in constants.default_config.items()}
		output_directory = os.path.expanduser(config["output-directory"])
		config["output-directory"] = output_directory
		return config

def main():
	def add_arguments_from_config(config, parser):
		for key, value in config.items():
			arguments = {}
			if type(value) == bool:
				arguments["action"] = "store_true"
			else:
				arguments["nargs"] = "?"
			parser.add_argument(f"--{key}", **arguments)

	parser = argparse.ArgumentParser()
	parser.add_argument("-c", "--config-file")
	add_arguments_from_config(constants.default_config, parser)
	handlers = {"song": song,
	            "album": album,
	            "discography": discography}
	subparsers = parser.add_subparsers(dest="query")
	subparsers.required = True
	for name, handler in handlers.items():
		subparser = subparsers.add_parser(name)
		subparser.add_argument("query", nargs="+")
		add_arguments_from_config(constants.default_config, subparser)
		subparser.set_defaults(func=handler)

	parsed_args = parser.parse_args()
	args = vars(parsed_args)
	config = load_config(args)

	log(config, "Authenticating...")
	client = authentication.authenticate(config)

	parsed_args.func(client, config, args["query"])
	log(config, "Done!")

def execute():
	try:
		main()
	except KeyboardInterrupt:
		sys.exit(1)
	finally:
		cursor.show()