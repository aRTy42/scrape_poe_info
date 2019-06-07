#! python3
"""
# scrape_poe_uniques.py - scrapes poe uniques from the wiki using the API
and then writes them, in their category, one per line.
"""

import requests, re, datetime, time, json, os

SCRIPTDIR = os.path.dirname(os.path.abspath(__file__))

# Regex magic! I recommend using https://regex101.com to make it more readable.

regex_wikilinks = re.compile(r'\[\[([^\]\|]*)\]\]|\[\[[^\]\|]*\|([^\]\|]*)\]\]')
"""
matches formats "[[mod]]" or "[[wikipage|mod]] and stores "mod" as capture group 1 or 2, respectively.
Since only one capture group is filled each time, using both together in a replacement like r'\1\2' turns
both match variants into "mod".
"""

regex_wiki_page_disamb = re.compile(r'([^\(]+) \([^\)]+\)')
"""
matches items named "item name (disambiguation)" and stores "item name" as capture group 1.
this format is used in the wiki to distinguish style variants of items, giving each variant its own page.
since the style variants ingame all have the same name, we want to filter these out and
put in a manually prepared version that covers all styles in one overview. 
"""

regex_single_range = re.compile(r'\+?\((-?[\d\.]+-[\d\.]+)\)%?')
"""
matches variants of the wiki's "(num-num)" format including the possibly leading "+" and trailing "%", such as:
	(10-20)
	+(10-20)
	(10-20)%
	(0.6-1)%
	(0.6-0.8)%
	(-40-40)%	format found in ventor's gamble's rarity and some "flask charge used" mods
	+(-25-50)%	ventor's gamble again, now with resistances
	
	The "num-num" part inside the brakets is stored as capture group 1
	
	It intentionally leaves the leading "-" of mods like "-(20-10) Physical Damage Taken from Attacks"
	The initial matching of double range damage mods like "Adds (10-20) to (30-40) Type Damage" is done
	with another expression.
"""

regex_double_range = re.compile(r'\(?(?P<lowmin>\d+)(?:-(?P<lowmax>\d+)\))? to \(?(?P<highmin>\d+)(?:-(?P<highmax>\d+)\))?')
"""
matches the relevant variants for double range damage mods
(10-20) to (30-40)
15 to (30-40)
(10-20) to 35
15 to 35

Four named capture groups are used: lowmin, lowmax, highmin and highmax (numbers 10, 20, 30 and 40 above)
lowmax and/or highmax is None if the part is only a number and not a number range (cases 2-4 above; numbers 15 and 35)
"""

def filter_unicode_string(str):
	return str.replace(u'\u2212', '-').replace(u'\u2013', '-').strip()


def remove_wiki_formats(text):
	if text is None:
		return None
	
	text = regex_wikilinks.sub(r'\1\2', text)	# remove wiki links with regular expression. See the start of the script.
	text = text.replace('&lt;em class=&quot;tc -corrupted&quot;&gt;Corrupted&lt;/em&gt;', 'Corrupted')	# remove corrupted markup
	text = text.replace('&amp;#60;', '<').replace('&amp;#62;', '>')
	text = text.replace('&lt;', '<').replace('&gt;', '>')
	text = text.replace('<br />', ' ')
	return text

	
def clean_up_api_results(api_results):
	"""
	Takes the API result and turns it into a list of json objects.
	Each object gets the three keys 'name', 'impl' and 'expl'.
	At this stage the mods are still full of wiki formatting and
	technical annotations, like mods marked with '(Hidden)'.
	Note that the explicit mods of an item are also still in a single string,
	with '<br>' seperating them.	
	"""
	
	#item_names = list(api_results.keys())
	#item_names.sort()
	partial_item_list = []
	for result in api_results:
		itemdata = result['title']
		obj = {}
		obj['name'] = itemdata['name']
		impl = itemdata['implicit stat text']		# returns a list with one entry or an empty list
		if not impl:
			impl = None
		obj['impl'] = remove_wiki_formats(impl)
		expl = itemdata['explicit stat text']	# explicit mods are also in one long entry
		if not expl:
			expl = None
		obj['expl'] = remove_wiki_formats(expl)
		partial_item_list.append(obj)
	
	return partial_item_list
	
	
def get_api_results(item_category):
	"""
	This function gets the wiki data for given unique item categories.
	It uses the wiki's API and requests json format.
	See this HTML version for belts to get a better idea how the API response is structured:
	https://pathofexile.gamepedia.com/api.php?action=cargoquery&format=json&limit=500&tables=items&fields=name%2Cimplicit_stat_text%2Cexplicit_stat_text&where=rarity%3D%22unique%22+AND+class%3D%22Belts%22&group_by=items._pageName&formatversion=1
	"""
	
	print('Getting data for ' + item_category)
	if item_category is 'Maps':
		r = requests.get('https://pathofexile.gamepedia.com/api.php?action=cargoquery&format=json&limit=500&tables=items&fields=items.name%2C+items.implicit_stat_text%2C+items.explicit_stat_text&where=items.rarity%3D%22unique%22+AND+items.class%3D%22Maps%22+AND+(_pageName+LIKE+%22%25(War+for+the+Atlas)%22+OR+_pageName+NOT+LIKE+%22%25(%25)%22)&group_by=items._pageName&formatversion=1')
	else:
		r = requests.get('https://pathofexile.gamepedia.com/api.php?action=cargoquery&format=json&limit=500&tables=items&fields=name%2Cimplicit_stat_text%2Cexplicit_stat_text&where=rarity%3D%22unique%22+AND+class%3D%22' + item_category + '%22&group_by=items._pageName&formatversion=1')
	
	rj = r.json()
	api_results = rj['cargoquery']
	
	return clean_up_api_results(api_results)


def get_wiki_data(item_categories):
	item_list = []
	for category in item_categories:
		item_list.extend(get_api_results(category))
	
	return item_list


def upcase_first_letter(string):
	return string[0].upper() + string[1:]


def	separate_num_ranges(mod_list):
	"""
	Takes a list of mods and modifies the entries to match the desired format for 
	the PoE Item Info Script's "Uniques.txt" file.
	This means mods with a randomly rolled range are changed, such as
	"+(80-100) to maximum Life" into "80-100:To maximum Life"
	
	Static mods like "50% increased Global Critical Strike Chance" remain as is.
	"""
	
	new_mod_list = []
	for mod in mod_list:
		num_part = regex_double_range.search(mod)
		if num_part is not None:
			lowmin = num_part.group('lowmin')
			lowmax = num_part.group('lowmax')
			highmin = num_part.group('highmin')
			highmax = num_part.group('highmax')
			if lowmax is None and highmax is None:		# Static case, it is the "Add 15 to 35 Type Damage" format
				num_part = ''
				text_part = mod
			else:
				if lowmax is None:
					lowmax = lowmin
				if highmax is None:
					highmax = highmin
				
				num_part = lowmin +'-'+ lowmax +','+ highmin +'-'+ highmax
				if not (int(lowmin) <= int(lowmax) and int(lowmax) <= int(highmin) and int(highmin) <= int(highmax)):		# debug stuff
					print('Double range oddity found. Will be written to file as: ' + num_part)
				
				text_part = regex_double_range.sub('', mod).strip().replace('  ', ' ')
				text_part = upcase_first_letter(text_part)
			
			# end of double range section

		else:
			num_part = regex_single_range.search(mod)
			if num_part is not None:
				num_part = num_part.group(1)
				if num_part[0] == '-':		# if the first number is negative, the output looks like '-10-20'
					num_part = num_part.replace('-', '-+').replace('-+', '-', 1)
					# we replace both - with +- and then the first back, which gives us a less ambiguous '-10-+20'
				
				text_part = regex_single_range.sub('', mod).strip().replace('  ', ' ')
				text_part = upcase_first_letter(text_part)
			else:
				num_part = ''
				text_part = mod
		
		new_mod = num_part + ':' + text_part
		
		new_mod_list.append(new_mod)
	
	return new_mod_list


def remove_hidden_mods(mod_list):
	new_mod_list = []
	for mod in mod_list:
		if '(Hidden)' not in mod:			# No '(Hidden)' annotation found
			new_mod_list.append(mod)		# Thus the mod is passed on
	
	return new_mod_list			


def	convert_to_AHK_script_format(item_list):
	"""
	Takes a list of json objects, holding the item informations.
	Parses items one by one and creates a list with text lines in the format
	for the PoE Item Info Script's "Uniques.txt" file.
	"""
	
	new_data = []
	
	# manually prepared formatting for style variant items
	with open(SCRIPTDIR + '\\UniqueStyleVariants.json', 'r') as f:
		prepared_style_variants = json.load(f)
	
	style_variant_included = []
		
	for item in item_list:
		item_name = item['name']
		if item_name in prepared_style_variants:
			if item_name not in style_variant_included:
				mod_line = prepared_style_variants[item_name]
				new_data.append(mod_line)
				style_variant_included.append(item_name)
				continue		# skip the rest of the loop because mod line was added properly
			else:
				continue		# skip the rest of the loop because style variant was already added
		else:
			mod_line = item['name']
		
		if item['impl']:
			impl_mod_list = item['impl'].split('<br>')
			impl_mod_list = remove_hidden_mods(impl_mod_list)
			
			if impl_mod_list:		# mod list is not empty
				impl_mod_list = separate_num_ranges(impl_mod_list)
				mod_line += '|@' + '|@'.join(impl_mod_list)		# Almost always there is no or only one implicit
				at_count = mod_line.count('|@')
				
				if at_count > 1:						# in case there were several implicits we now remove all @ except the last one
					mod_line = mod_line.replace('|@', '|', at_count-1)
					print('Multiple implicits on item: ' + item['name'])		# and print a warning to double check afterwards
		
		if item['expl']:
			expl_mod_list = item['expl'].split('<br>')
			expl_mod_list = remove_hidden_mods(expl_mod_list)
			
			if expl_mod_list:		# mod list is not empty
				expl_mod_list = separate_num_ranges(expl_mod_list)
				mod_line += '|' + '|'.join(expl_mod_list)

		new_data.append(mod_line)
	
	print('\nManually prepared style variants included for these items:\n' + '\n'.join(style_variant_included) + '\n(Make sure they are still correct)\n')
	
	return new_data


def define_file_header():
	"""
	info header for Uniques.txt

	:return: list
	"""
	data = []
	d = datetime.datetime.now()
	now_time = d.strftime('%Y-%m-%d at %H:%M:%S')
	data.append('; Data from https://pathofexile.gamepedia.com/Path_of_Exile_Wiki using the API.')
	data.append('; The "@" symbol marks a mod as implicit. This means a separator line will be appended after this mod. If there are multiple implicit mods, mark the last one in line.')
	data.append('; Comments can be made with ";", blank lines will be ignored.')
	data.append(';')
	data.append('; This file was auto-generated by scrape_poe_uniques.py on {}'.format(now_time))
	data.append('\n')

	return data


def write_list_to_lines(new_data):
	file = open(SCRIPTDIR + '\\Uniques.txt', 'a+b')  # opens file for writing
	for row in new_data:
		file.write(row.encode('cp1252'))
		file.write(b'\n')
	file.close()


def main():
	item_categories = ['Amulets','Belts','Rings','Quivers','Body Armours','Boots','Gloves','Helmets','Shields','One Hand Axes','Two Hand Axes','Bows','Claws','Daggers','Fishing Rods','One Hand Maces','Sceptres','Two Hand Maces','Staves','One Hand Swords','Thrusting One Hand Swords','Two Hand Swords','Wands','Life Flasks','Mana Flasks','Hybrid Flasks','Utility Flasks','Jewel','Maps']
	open(SCRIPTDIR + '\\Uniques.txt', 'w').close()  # create file (or overwrite it if it exists)
	write_list_to_lines(define_file_header())
	item_list = get_wiki_data(item_categories)
	new_data = convert_to_AHK_script_format(item_list)
	write_list_to_lines(new_data)
	

startTime = datetime.datetime.now()
main()
print('Program execution time: ',(datetime.datetime.now() - startTime))
