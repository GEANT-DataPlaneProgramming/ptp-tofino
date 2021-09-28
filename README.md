This repository contains work being done to implement the Precision Time Protocol (IEEE 1588) on the Tofino ASIC. The code is not yet compatible with the standard but rather is a proof of concept to show that Tofino ASIC provides the necessary functionality to implement PTP.

## Requirements

- SDE version => 9.5.0
- Thrift (=> 0.10.0 for Python 3 support)
- Python 2/3 Thrift library

## Generate Thrift code for Python

~~~
thrift --gen py $SDE/pkgsrc/bf-drivers/pdfixed_thrift/thrift/ts_pd_rpc.thrift
thrift --gen py $SDE/pkgsrc/bf-drivers/pdfixed_thrift/thrift/res.thrift
~~~
