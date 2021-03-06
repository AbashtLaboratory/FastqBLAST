#!/usr/bin/python3

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# - - - - - H E A D E R - - - - - - - - - - - - - - - - - - -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

"""
AUTHOR:         Danielle Novick

DATE CREATED:   October 24, 2017
LAST UPDATE:    February 15, 2018

OBJECTIVE:      This script takes a sample of sequences from a fastq file, trims the low quality ends, BLASTs them,
                fetches additional info from NCBI, and produces a report.

NCBI's BLAST Usage Guidelines
https://blast.ncbi.nlm.nih.gov/Blast.cgi?CMD=Web&PAGE_TYPE=BlastDocs&DOC_TYPE=DeveloperInfo

BioPython's Manual
http://biopython.org/DIST/docs/tutorial/Tutorial.html
"""

import sys
import random
import argparse
import time
from collections import defaultdict
from Bio.Blast import NCBIWWW
from Bio.Blast import NCBIXML
from Bio import Entrez, SeqIO
from urllib.error import HTTPError


# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# - - - - - G L O B A L  D E C L A R A T I O N S  - - - - - -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

entryLine = "\n\n* * * * * alpha snail on the trail * * * * *\n\n"
exitLine = "\n\n* * * * * beta toad on the road * * * * *\n\n"

parser = argparse.ArgumentParser(description='This script takes a sample of sequences from a fastq file, trims the \
                                low quality ends, BLASTs them, fetches additional info from NCBI, and produces a report.')

# positional arguments
parser.add_argument('filename', action="store", type=str,
                     help='The filename of the fastq file you wish to sample and BLAST')

# required named arguments
requiredNamed = parser.add_argument_group('required named arguments')
requiredNamed.add_argument('--email','-e', action="store", type=str, required=True,
                           help='A valid email address is required to use NCBI tools and will be used if NCBI observes \
                           requests that violate their policies.')

# optional arguments
parser.add_argument('--ascii64','-a', action="store", default=False, type=bool,
                     help='Select true if Phred quality scores are encoded as ASCII 64 (most are ASCII 33), '
                          'default is False')
parser.add_argument('--nPercent','-np', action="store", default=0, type=float,
                     help='A float between 0 and 100, this argument takes precedence over nAbsolute, default is 0')
parser.add_argument('--nAbsolute','-na', action="store", default=100, type=int,
                     help='An integer between 0 and the number of sequences in your fastq file, this argument is '
                          'superseded by nPercent, default is 100')
parser.add_argument('--leadingQ','-lq', action="store", default=20, type=int,
                     help='The minimum quality required to keep a base at the leading end of a read, default is 20')
parser.add_argument('--trailingQ','-tq', action="store", default=20, type=int,
                     help='The minimum quality required to keep a base at the trailing end of a read, default is 20')
parser.add_argument('--hitlistSize','-hs', action="store", default=1, type=int,
                     help='The number of blast hits to keep for the final report, default is 1')

args = parser.parse_args()

Entrez.email = args.email


# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# - - - - - M A I N - - - - - - - - - - - - - - - - - - - - -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -


def random_sample(fastq_filename, n_absolute, n_percent):
    """
    Counts the number of lines/sequences in a FASTQ file and then takes a sample that can be entered either as a percent
    or an absolute number (the percent supersedes the absolute if both are entered).

    :param fastq_filename: The name of a fastq file
    :param n_absolute: An absolute number of samples that will be taken, superseded by n_percent if that's larger than 0
    :param n_percent: A percent of samples that will be taken, if this is specified it will take precedence over n_absolute
    :return: a list of integers that correspond to the first line of each sequence that is in the sample
    """
    with open(fastq_filename) as file:
        for counter, line in enumerate(file, 1):  # start index at 1 instead of 0
            pass
    num_lines = counter
    num_sequences = int(num_lines/4)
    print("You have %s sequences in your FASTQ file.\n" % "{:,}".format(num_sequences))
    sample_size = n_absolute if n_percent == 0 else int(n_percent*num_sequences/100)
    if sample_size > num_sequences:
        print("Your sample size is greater than your population size. Please select a number less than %s or consider "
              "using the percentage parameter." % "{:,}".format(num_sequences))
        sys.exit()
    elif sample_size == 0:
        print("You're trying to take a sample of size 0. Please adjust either nPercent or nAbsolute to correct the issue.")
        sys.exit()
    else: print("Sampling %s sequences from your file..." % "{:,}".format(sample_size))
    sample_set = [x * 4 for x in random.sample(range(0,int(num_lines/4)), sample_size)]
    return sample_set


def fastq_to_dict(fastq_filename, sample_list):
    """
    Uses a list of sequence starting lines to pull out sequences from a fastq file and stores them in a dictionary,
    then decodes the phred scores and stores those as well

    :param fastq_filename: The name of a fastq file
    :param sample_list: A list of integers that correspond to the first line of each sequence that is in the sample
    :return: a two-level defaultdict {header:{'sequence': }, {'ascii':}, {'phred'}}
    """
    sample_dict = defaultdict(lambda: defaultdict())
    with open(fastq_filename) as file:
        for counter, line in enumerate(file):
            if counter in sample_list:
                header = line.rstrip().split("\t")[0]
            elif (counter - 1) in sample_list:
                sample_dict[header]['sequence'] = line.rstrip()
            elif (counter - 3) in sample_list:
                sample_dict[header]['ascii'] = line.rstrip()
    base = 33 if args.ascii64 == False else 64
    for key in sample_dict.keys():
        sample_dict[key]['phred'] = [ord(x) - base for x in list(sample_dict[key]['ascii'])]
    return sample_dict


def trim_ends(sample_dictionary, leadingQthreshold, trailingQthreshold):
    """
    Trims low quality bases from the leading and trailing ends of sequences

    :param sample_dictionary:   a two-level defaultdict {header:{'sequence': }, {'ascii':}, {'phred'}}
    :param leadingQthreshold:   the minimum quality required to keep a base at the leading end of a read
    :param trailingQthreshold:  the minimum quality required to keep a base at the trailing end of a read
    :return: the parameter sample_dictionary, but with two additional keys (trimmed_phred and trimmed_sequence)
    """
    print("Trimming the low-quality ends...")
    sample_dict = sample_dictionary.copy()
    for key in sample_dict.keys():
        for base, Q in enumerate(sample_dict[key]['phred']):
            if Q < leadingQthreshold:
                continue
            else:
                sample_dict[key]['trimmed_phred'] = sample_dict[key]['phred'][base:]
                sample_dict[key]['trimmed_sequence'] = sample_dict[key]['sequence'][base:]
                break
        for base, Q in reversed(list(enumerate(sample_dict[key]['phred']))):
            if Q < trailingQthreshold:
                continue
            else:
                sample_dict[key]['trimmed_phred'] = sample_dict[key]['trimmed_phred'][:base+1]
                sample_dict[key]['trimmed_sequence'] = sample_dict[key]['trimmed_sequence'][:base+1]
                break
    return sample_dict


def write_fasta(sample_dictionary):
    """
    Writes a FASTA file with the sequence IDs and trimmed sequences from the sample dictionary

    :param sample_dictionary:  a two-level defaultdict with information about the sequences to be BLASTed
    :return: blast_queries.fasta
    """
    OUT = open('blast_queries.fasta', 'w')
    for key in sample_dictionary:
        # failsafe for sequences that are trimmed to be 0 bases long
        if 'trimmed_sequence' in  sample_dictionary[key].keys():
            OUT.write('>' + key[1:] + '\n' + sample_dictionary[key]['trimmed_sequence'] + '\n')
    OUT.close()


def blast_reads(number_hits):
    """
    Uses Biopython's qblast() to BLAST sequences from a FASTA file, then write the blast results to a file

    :param number_hits: The maximum number of hits to return for each BLAST query sequence
    :return: blast_results.xml
    """
    print("Searching for BLAST hits...")
    fasta_string = open("blast_queries.fasta").read()
    result_handle = NCBIWWW.qblast("blastn", "nt", fasta_string, hitlist_size=number_hits)
    blast_result = open("blast_results.xml", "w")
    blast_result.write(result_handle.read())
    blast_result.close()
    result_handle.close()


def blast_to_dict():
    """
    Parses BLAST results and stores useful information in a dictionary. Throws an error if the blast_results.xml file
    only contains the queries with no results, which is an indicator that the BLAST was rejected by NCBI

    :return: a two-level defaultdict with information from the BLAST results and a flat list of the genes identified by BLAST
    """
    print("Parsing the BLAST results...")
    GeneIDs = []
    blast_dict = defaultdict(lambda: defaultdict())
    for record in NCBIXML.parse(open("blast_results.xml")):
        for align in record.alignments:
            for hsp in align.hsps:
                percent_identity = round(100 * float(hsp.identities) / float(hsp.align_length),2)  # https://www.dnastar.com/megalign_help/index.html#!Documents/calculationofpercentidentity.htm
                hit_id = align.title.split('|')
                # this uses NCBI's gi number (GenInfo Identifier) which is reliable now but getting phased out, so might
                # need to change to hit_id[3] at some point
                GeneIDs.append(hit_id[1])
                blast_dict[align.title]['SeqID'] = record.query
                blast_dict[align.title]['Sequence'] = hsp.query
                blast_dict[align.title]['SeqLength'] = len(hsp.query)
                blast_dict[align.title]['Description'] = hit_id[4]
                blast_dict[align.title]['Accession'] = hit_id[3]
                blast_dict[align.title]['Db'] = hit_id[2]
                blast_dict[align.title]['Score'] = hsp.score
                blast_dict[align.title]['E_value'] = hsp.expect
                blast_dict[align.title]['Percent_Identity'] = percent_identity
    GeneIDs = list(set(GeneIDs))
    if not GeneIDs:
        print('\nYour BLAST query was rejected. Please enter a smaller sample size or try running this script \
              at a better time.\nNCBI asks that you run scripts on weekends or between 9pm and 5am Eastern \
              time on weekdays if more than 50 searches will be submitted.')
        sys.exit()
    return blast_dict, GeneIDs


def fetch_gene_info(gene_list, batch_size=100):
    """
    Uses an NCBI tool called efetch to look up more information about the genes identified by BLAST, then writes
    the results to a file. Epost is used here as good practice for large submissions to efetch

    :param gene_list: a list of NCBI gi's that will be submitted to efetch
    :param batch_size: the size of batches of gi's that get submitted to efetch to prevent overloading it
    :return: fetch_results.txt
    """
    print("Looking up additional information about the genes identified by BLAST...")
    post_handle = Entrez.epost(db="nucleotide", id=",".join(gene_list))
    result = Entrez.read(post_handle)
    post_handle.close()
    webenv = result["WebEnv"]
    query_key = result["QueryKey"]
    count = len(gene_list)
    OUT = open("fetch_results.txt", "w")
    for start in range(0, count, batch_size):
        end = min(count, start + batch_size)
        print("Fetching records %i through %i" % (start + 1, end))
        attempt = 0
        while attempt < 3:
            attempt += 1
            try:
                fetch_handle = Entrez.efetch(db="nucleotide", rettype="gb", retmode="text", retstart=start, retmax=batch_size,
                                            webenv=webenv, query_key=query_key)
            except HTTPError as err:
                if 500 <= err.code <= 599:
                    print("Received error from server %s" % err)
                    print("Attempt %i of 3" % attempt)
                    time.sleep(15)
                else:
                    raise
        OUT.write(fetch_handle.read())
        fetch_handle.close()
    OUT.close()


def fetch_to_dict(blast_dictionary):
    """
    Stores information from an efetch results file into a dictionary and then merges that dictionary with the BLAST
    results dictionary

    :param blast_dictionary: a two level dictionary containing results from a BLAST search
    :return: the blast_dictionary parameter, but with additional keys (Organism, Source, Domain, Taxonomy)
    """
    blast_dict = blast_dictionary.copy()
    fetch_dict = defaultdict(lambda: defaultdict())
    for record in SeqIO.parse("fetch_results.txt", "genbank"):
        fetch_dict[record.id]['Organism'] = record.annotations['organism']
        fetch_dict[record.id]['Source'] = record.annotations['source']
        fetch_dict[record.id]['Domain'] = record.annotations['taxonomy'][0]
        fetch_dict[record.id]['Taxonomy'] = record.annotations['taxonomy']
    for record in blast_dict.keys():
        for accession in fetch_dict.keys():
            if accession in blast_dict[record]["Accession"]:
                for accession_item in next(iter(fetch_dict.values())).keys():
                    blast_dict[record][accession_item] = fetch_dict[accession][accession_item]
    return blast_dict


def tabular_report(sample_dictionary, blast_dictionary):
    """
    Writes a report about the sample set using information from BLAST and eFetch

    :param sample_dictionary: a two-level defaultdict with information about the sequences from a fastq file
    :param blast_dictionary: a two level dictionary containing results from a BLAST search and eFetch
    :return: blast_report.txt
    """
    print("Writing the report...")
    sample_dict = sample_dictionary.copy()
    blast_dict = blast_dictionary.copy()
    samples = []
    for sequenceID in sample_dict:
        samples.append(sequenceID[1:])
    records = []
    for record in blast_dict.keys():
        records.append(blast_dict[record]['SeqID'])
    columns = ["SeqID", "Sequence", "SeqLength", "Description", "Accession", "Db", "Score", "E_value", "Percent_Identity", "Organism", "Source", "Domain", "Taxonomy"]
    # columns = list(next(iter(blast_dict.values())).keys())
    OUT = open("blast_report.txt", "w")
    OUT.write('\t'.join(columns) + '\n')
    for record in blast_dict.keys():
        OUT.write('\t'.join([str(blast_dict[record][x]) for x in columns]) + '\n')
    for sample in samples:
        if sample not in records:
            sample_stripped = sample.split("\t")[0]
            OUT.write(sample_stripped + '\t' + sample_dict['@'+sample]['sequence'] + '\t' + str(len(sample_dict['@'+sample]['sequence'])) + '\t' + 'NO HIT OR SEQUENCE QUALITY BELOW THRESHOLD\n')
    OUT.close()


def main():
    print(entryLine)
    sample_set = random_sample(fastq_filename=args.filename, n_absolute=args.nAbsolute, n_percent=args.nPercent)
    sample_dict = fastq_to_dict(fastq_filename=args.filename, sample_list=sample_set)
    sample_dict = trim_ends(sample_dictionary=sample_dict,leadingQthreshold=args.leadingQ, trailingQthreshold=args.trailingQ)
    write_fasta(sample_dictionary=sample_dict)
    blast_reads(number_hits=args.hitlistSize)
    blast_dict, GeneIDs = blast_to_dict()
    fetch_gene_info(gene_list=GeneIDs)
    blast_dict = fetch_to_dict(blast_dictionary=blast_dict)
    tabular_report(sample_dictionary=sample_dict, blast_dictionary=blast_dict)
    print(exitLine)


if __name__ == "__main__":
    main()


# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -
# - - - - - E n d   o f   F i l e - - - - - - - - - - - - - -
# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

