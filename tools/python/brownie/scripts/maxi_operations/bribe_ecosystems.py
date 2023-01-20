import requests
from decimal import Decimal, InvalidOperation

from brownie import web3, interface
from web3 import Web3
from great_ape_safe import GreatApeSafe
from helpers.addresses import r
import csv


SNAPSHOT_URL = "https://hub.snapshot.org/graphql?"
HH_API_URL = "https://hhand.xyz/proposal"

#TODO The most up to date file has not been merged to master so using a blog link instead
#GAUGE_MAPPING_URL = "https://raw.githubusercontent.com/aurafinance/aura-contracts/main/tasks/snapshot/labels.json"
GAUGE_MAPPING_URL = "https://raw.githubusercontent.com/aurafinance/aura-contracts/9f8fb6ff33a98f7f87262eaa6773c528e026f95d/tasks/snapshot/labels.json"

# queries for choices and proposals info
QUERY_PROPOSAL_INFO = """
query ($proposal_id: String) {
  proposal(id: $proposal_id) {
    choices
  }
}
"""

# `state: "all"` ensures all proposals are included
QUERY_PROPOSALS = """
query {
  proposals(first: 100, where: { space: "gauges.aurafinance.eth" , state: "all"}) {
    id
  }
}
"""

def get_hh_aura_target(target_name):
    response = requests.get(f"{HH_API_URL}/aura")
    options = response.json()["data"]
    for option in options:
        if option["title"] == target_name:
            return option["proposalHash"]
    return False  ## return false if no result

def get_gauge_name_map(map_url=GAUGE_MAPPING_URL):
    ## the url was not responding on IPv6 addresses
    requests.packages.urllib3.util.connection.HAS_IPV6 = False

    response = requests.get(map_url)
    item_list = response.json()
    output = {}
    for mapping in item_list:
        gauge_address = web3.toChecksumAddress(mapping["gauge"])
        output[gauge_address] = mapping["label"]
    return output

def get_index(proposal_id, target):
    # grab data from the snapshot endpoint re proposal choices
    response = requests.post(
        SNAPSHOT_URL,
        json={
            "query": QUERY_PROPOSAL_INFO,
            "variables": {"proposal_id": proposal_id},
        },
    )
    choices = response.json()["data"]["proposal"]["choices"]
    choice = choices.index(target)
    return choice

def process_bribe_csv(
       csv_file
):
    # Process the CSV
    # csv_format: target, platform, amount
    bribe_csv = csv.DictReader(open(csv_file))
    aura_bribes = []
    balancer_bribes = []
    bribes = {
        "aura": {},
        "balancer": {}
    }
    ## Parse briibes per platform
    for bribe in bribe_csv:
        bribes[bribe["platform"]][bribe["target"]] = float(bribe["amount"])
    return bribes

def main(
    csv_file="bribes/csv/current.csv",
):

    safe = GreatApeSafe(r.balancer.multisigs.dao)
    usdc = safe.contract(r.tokens.USDC)

    safe.take_snapshot([usdc])

    bribe_vault = safe.contract(r.hidden_hand.bribe_vault, interface.IBribeVault)
    aura_briber = safe.contract(r.hidden_hand.aura_briber, interface.IAuraBribe)
    balancer_briber = safe.contract(
        r.hidden_hand.balancer_briber, interface.IBalancerBribe
    )
    bribes = process_bribe_csv(csv_file)
    ### BALANCER
    def bribe_balancer(gauge, mantissa):
        prop = web3.solidityKeccak(["address"], [Web3.toChecksumAddress(gauge)])
        mantissa = int(mantissa)

        usdc.approve(bribe_vault, mantissa)

        print("*** Posting Balancer Bribe:")
        print("*** Gauge Address:", gauge)
        print("*** Proposal hash:", prop.hex())
        print("*** Amount:", amount)
        print("*** Mantissa Amount:", mantissa)
        print("\n")


        balancer_briber.depositBribeERC20(
            prop,  # bytes32 proposal
            usdc,  # address token
            mantissa,  # uint256 amount
        )

    for target, amount in bribes["balancer"].items():
        decimals = 10**int(usdc.decimals())
        mantissa = int(amount * decimals)
        bribe_balancer(target, mantissa)

    ### AURA
    gauge_address_to_snapshot_name = get_gauge_name_map()
    for target, amount in bribes["aura"].items():
        target_name = gauge_address_to_snapshot_name[web3.toChecksumAddress(target)]
        # grab data from proposals to find out the proposal index
        prop = get_hh_aura_target(target_name)
        decimals = 10 ** int(usdc.decimals())
        mantissa = int(amount * decimals)
        # NOTE: debugging prints to verify
        print("*** Posting AURA Bribe:")
        print("*** Target Gauge Address:", target)
        print("*** Target Gauge Address:", target_name)
        print("*** Proposal hash:", prop)
        print("*** Amount:", amount)
        print("*** Mantissa Amount:", mantissa)
        print("\n")


        usdc.approve(bribe_vault, mantissa)
        aura_briber.depositBribeERC20(
            prop,  # bytes32 proposal
            usdc,  # address token
            mantissa,  # uint256 amount
        )

    print("\n\nBuilding and pushing multisig payload")
    ### DO IT
    safe.post_safe_tx(gen_tenderly=False)
