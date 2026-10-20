#include <OpenMS/FORMAT/ImzMLFile.h>
#include <iostream>
int main(int argc,char**argv){try{OpenMS::ImzMLMeta meta;std::vector<OpenMS::ImzMLSpectrumIndex>index;OpenMS::ImzMLFile().loadSpectraIndex(argv[1],meta,index);std::cout<<"INDEX OK "<<index.size()<<"\n";}catch(std::exception&e){std::cerr<<e.what()<<"\n";return 1;}}
